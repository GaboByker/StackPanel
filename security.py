"""Seguridad del panel: registro de intentos de acceso, bloqueo automático y
manual de IPs, lista blanca y reglas configurables desde /admin/security.

Todo vive en la base de datos (tablas ip_bans, ip_allowlist, auth_events y
claves sec_* en settings) para que sea la única fuente de verdad: hoy la usa
el propio panel para bloquear su login, y más adelante el agente del host
(stackpanel-guard) leerá estas mismas tablas para llevar los bloqueos a
nftables y extenderlos a SSH/SFTP/nginx.

Reglas anti-bloqueo propio:
  - Una IP en la lista blanca nunca se bloquea (ni automática ni manualmente).
  - No se puede bloquear a mano un rango que contenga la IP desde la que estás.
"""
import ipaddress
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import guard_client
import notification_control
import panel_db

# Valores por defecto de las reglas; cada uno se puede cambiar desde el panel.
# (clave, defecto, mínimo, máximo)
RULES = {
    'sec_max_failures': (5, 1, 100),          # fallos por IP antes de bloquearla
    'sec_window_minutes': (10, 1, 1440),      # ventana en la que se cuentan
    'sec_ban_minutes': (30, 1, 525600),       # duración del primer bloqueo
    'sec_ban_multiplier': (2, 1, 10),         # cada reincidencia multiplica la duración
    'sec_ban_max_minutes': (10080, 1, 525600),  # techo del bloqueo automático (7 días)
    'sec_account_max_failures': (10, 1, 1000),  # fallos por cuenta (desde cualquier IP)
    'sec_session_hours': (12, 1, 168),        # vida máxima de una sesión
    'sec_idle_minutes': (60, 5, 10080),       # cierre por inactividad
    'sec_require_2fa': (0, 0, 1),             # exigir 2FA a todos los admins
}

# Mismo criterio que aplica el agente del host: rangos más amplios que esto
# no se bloquean (un /8 por error dejaría fuera a medio país).
MIN_BAN_PREFIX = {4: 16, 6: 48}

# Detección automática en el servidor (la ejecuta stackpanel-guard, ver
# guard/detector.py, que trae los mismos valores por defecto).
JAILS = {
    'sshd': {
        'label': 'SSH del servidor', 'source': 'journald (sshd)',
        'defaults': {'mode': 'ban', 'max_failures': 5, 'window_minutes': 10, 'ban_minutes': 60},
    },
    'sftp': {
        'label': 'SFTP de proyectos', 'source': 'logs del contenedor SFTP',
        'defaults': {'mode': 'ban', 'max_failures': 5, 'window_minutes': 10, 'ban_minutes': 60,
                     'container': 'stackpanel-sftp'},
    },
    'nginx': {
        'label': 'Webs (proxy nginx)', 'source': 'access log del contenedor del proxy',
        'defaults': {'mode': 'observe', 'max_failures': 10, 'window_minutes': 10, 'ban_minutes': 1440,
                     'container': os.environ.get('PROXY_CONTAINER', 'proxy')},
    },
}
JAIL_MODES = {'off': 'Apagado', 'observe': 'Solo observar', 'ban': 'Bloquear'}
SERVICE_LABELS = {'panel': 'Panel', 'sshd': 'SSH', 'sftp': 'SFTP', 'nginx': 'Web'}
_CONTAINER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')

EVENT_RETENTION_DAYS = 30
RECIDIVE_LOOKBACK_DAYS = 30
_PENDING_2FA_MAX_TRIES = 5


def _connect(root):
    return panel_db._connect(root)


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat() if dt else None


def init_db(root):
    with _connect(root) as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS auth_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                ip TEXT NOT NULL,
                service TEXT NOT NULL DEFAULT 'panel',
                kind TEXT NOT NULL,
                email TEXT,
                success INTEGER NOT NULL,
                user_agent TEXT
            )
            '''
        )
        ev_cols = {r[1] for r in conn.execute('PRAGMA table_info(auth_events)')}
        if 'detail' not in ev_cols:
            conn.execute('ALTER TABLE auth_events ADD COLUMN detail TEXT')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_auth_events_ip_ts ON auth_events(ip, ts)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_auth_events_service_ts ON auth_events(service, ts)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_auth_events_email_ts ON auth_events(email, ts)')
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS ip_bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cidr TEXT NOT NULL,
                service TEXT NOT NULL DEFAULT 'panel',
                source TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                created_by TEXT,
                lifted_at TEXT,
                lifted_by TEXT
            )
            '''
        )
        ban_cols = {r[1] for r in conn.execute('PRAGMA table_info(ip_bans)')}
        if 'notified' not in ban_cols:
            # Los bloqueos previos a esta columna se dan por avisados.
            conn.execute('ALTER TABLE ip_bans ADD COLUMN notified INTEGER NOT NULL DEFAULT 0')
            conn.execute('UPDATE ip_bans SET notified = 1')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_ip_bans_active ON ip_bans(lifted_at, expires_at)')
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS ip_allowlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cidr TEXT NOT NULL UNIQUE,
                note TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT
            )
            '''
        )


# --- utilidades de IP ---------------------------------------------------------

def parse_network(value):
    """Acepta una IP suelta o un rango CIDR (v4 o v6). Devuelve el texto
    normalizado, o None si no es válido."""
    value = (value or '').strip()
    if not value:
        return None
    try:
        return str(ipaddress.ip_network(value, strict=False))
    except ValueError:
        return None


def _in_any(ip, cidrs):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _trusted_proxies():
    raw = os.environ.get('PORTAL_TRUSTED_PROXIES', '')
    return [c for c in (parse_network(x) for x in raw.split(',')) if c]


def client_ip(request):
    """IP real del cliente. Solo se cree en X-Forwarded-For si la conexión
    llega desde un proxy declarado en PORTAL_TRUSTED_PROXIES (si no, cualquiera
    podría falsificar la cabecera y esquivar los bloqueos)."""
    remote = request.remote_addr or ''
    proxies = _trusted_proxies()
    if proxies and _in_any(remote, proxies):
        forwarded = [p.strip() for p in request.headers.get('X-Forwarded-For', '').split(',') if p.strip()]
        # Se recorre de derecha a izquierda saltando proxies propios: el
        # primero que no sea de confianza es el cliente real.
        for hop in reversed(forwarded):
            if not _in_any(hop, proxies):
                try:
                    return str(ipaddress.ip_address(hop))
                except ValueError:
                    break
    return remote


# --- reglas -------------------------------------------------------------------

def get_rules(root):
    stored = panel_db.get_settings(root, list(RULES))
    rules = {}
    for key, (default, lo, hi) in RULES.items():
        try:
            value = int(stored.get(key, default))
        except (TypeError, ValueError):
            value = default
        rules[key] = min(max(value, lo), hi)
    return rules


def save_rules(root, form):
    values = {}
    for key, (default, lo, hi) in RULES.items():
        if key == 'sec_require_2fa':
            values[key] = '1' if form.get(key) == 'on' else '0'
            continue
        try:
            value = int((form.get(key) or '').strip())
        except ValueError:
            return False, f'Valor no válido en "{key}".'
        if not lo <= value <= hi:
            return False, f'"{key}" debe estar entre {lo} y {hi}.'
        values[key] = str(value)
    panel_db.set_settings(root, values)
    return True, None


# --- jails (detección en el servidor) -----------------------------------------

def get_jails(root):
    try:
        stored = json.loads(panel_db.get_setting(root, 'sec_jails') or '{}')
    except ValueError:
        stored = {}
    jails = {}
    for name, meta in JAILS.items():
        conf = dict(meta['defaults'])
        conf.update({k: v for k, v in (stored.get(name) or {}).items() if k in conf})
        jails[name] = {**conf, 'label': meta['label'], 'source': meta['source']}
    return jails


def ensure_jail_defaults(root):
    """Guarda la configuración de detección si todavía no existe, para que
    el agente del host use los nombres de contenedor de ESTA instalación
    (él no ve las variables de entorno del panel)."""
    if panel_db.get_setting(root, 'sec_jails'):
        return
    panel_db.set_settings(root, {'sec_jails': json.dumps(
        {name: dict(meta['defaults']) for name, meta in JAILS.items()}
    )})


def save_jails(root, form):
    stored = {}
    for name, meta in JAILS.items():
        conf = {}
        mode = form.get(f'{name}_mode', '')
        if mode not in JAIL_MODES:
            return False, f'Modo no válido para {meta["label"]}.'
        conf['mode'] = mode
        for key, lo, hi in (('max_failures', 1, 1000), ('window_minutes', 1, 1440), ('ban_minutes', 1, 525600)):
            try:
                value = int((form.get(f'{name}_{key}') or '').strip())
            except ValueError:
                return False, f'Valor no válido en {meta["label"]}.'
            if not lo <= value <= hi:
                return False, f'{meta["label"]}: los valores deben estar entre {lo} y {hi}.'
            conf[key] = value
        if 'container' in meta['defaults']:
            container = (form.get(f'{name}_container') or '').strip()
            if not _CONTAINER_RE.match(container):
                return False, f'{meta["label"]}: nombre de contenedor no válido.'
            conf['container'] = container
        stored[name] = conf
    panel_db.set_settings(root, {'sec_jails': json.dumps(stored)})
    guard_client.request_sync()
    return True, None


def jail_stats(root):
    """Fallos, bloqueos y casos 'observados' de las últimas 24 h por servicio."""
    since = _iso(_now() - timedelta(hours=24))
    with _connect(root) as conn:
        failures = dict(conn.execute(
            'SELECT service, COUNT(*) FROM auth_events WHERE success = 0 AND ts > ? GROUP BY service', (since,)
        ).fetchall())
        bans = dict(conn.execute(
            "SELECT service, COUNT(*) FROM ip_bans WHERE source = 'auto' AND created_at > ? GROUP BY service",
            (since,),
        ).fetchall())
        observed = conn.execute(
            "SELECT detail FROM audit_log WHERE action = 'jail_observe' AND ts > ?", (since,)
        ).fetchall()
    obs = {}
    for (detail,) in observed:
        obs[(detail or '').split(' · ')[0]] = obs.get((detail or '').split(' · ')[0], 0) + 1
    return {
        name: {'failures': failures.get(name, 0), 'bans': bans.get(name, 0), 'observed': obs.get(name, 0)}
        for name in list(JAILS) + ['panel']
    }


# --- lista blanca -------------------------------------------------------------

def list_allowlist(root):
    with _connect(root) as conn:
        rows = conn.execute('SELECT * FROM ip_allowlist ORDER BY id').fetchall()
    return [dict(r) for r in rows]


def is_allowlisted(root, ip):
    return _in_any(ip, [r['cidr'] for r in list_allowlist(root)])


def add_allowlist(root, value, note, admin_email):
    cidr = parse_network(value)
    if not cidr:
        return None, 'IP o rango no válido.'
    try:
        with _connect(root) as conn:
            conn.execute(
                'INSERT INTO ip_allowlist (cidr, note, created_at, created_by) VALUES (?, ?, ?, ?)',
                (cidr, (note or '').strip()[:200], _iso(_now()), admin_email),
            )
    except sqlite3.IntegrityError:
        return None, f'{cidr} ya está en la lista blanca.'
    # Lo que se acaba de declarar de confianza no puede seguir bloqueado.
    net = ipaddress.ip_network(cidr)
    for active in list_active_bans(root):
        if net.overlaps(ipaddress.ip_network(active['cidr'])):
            lift_ban(root, active['id'], admin_email)
    guard_client.request_sync()
    return cidr, None


def remove_allowlist(root, entry_id):
    with _connect(root) as conn:
        row = conn.execute('SELECT cidr FROM ip_allowlist WHERE id = ?', (entry_id,)).fetchone()
        conn.execute('DELETE FROM ip_allowlist WHERE id = ?', (entry_id,))
    guard_client.request_sync()
    return row['cidr'] if row else None


# --- bloqueos -----------------------------------------------------------------

def _active_clause():
    return 'lifted_at IS NULL AND (expires_at IS NULL OR expires_at > ?)'


def list_active_bans(root):
    with _connect(root) as conn:
        rows = conn.execute(
            f'SELECT * FROM ip_bans WHERE {_active_clause()} ORDER BY id DESC', (_iso(_now()),)
        ).fetchall()
    return [dict(r) for r in rows]


def list_ban_history(root, limit=50):
    with _connect(root) as conn:
        rows = conn.execute(
            f'SELECT * FROM ip_bans WHERE NOT ({_active_clause()}) ORDER BY id DESC LIMIT ?',
            (_iso(_now()), limit),
        ).fetchall()
    return [dict(r) for r in rows]


def is_banned(root, ip):
    if is_allowlisted(root, ip):
        return False
    return _in_any(ip, [b['cidr'] for b in list_active_bans(root)])


def ban(root, value, minutes, reason, source, admin_email=None, service='panel'):
    """minutes=None -> bloqueo permanente."""
    cidr = parse_network(value)
    if not cidr:
        return None, 'IP o rango no válido.'
    expires = _now() + timedelta(minutes=minutes) if minutes else None
    with _connect(root) as conn:
        conn.execute(
            'INSERT INTO ip_bans (cidr, service, source, reason, created_at, expires_at, created_by) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (cidr, service, source, (reason or '')[:300], _iso(_now()), _iso(expires), admin_email),
        )
    guard_client.request_sync()
    return cidr, None


def manual_ban(root, value, minutes, reason, admin_email, own_ip):
    cidr = parse_network(value)
    if not cidr:
        return None, 'IP o rango no válido.'
    if _in_any(own_ip, [cidr]):
        return None, f'No puedes bloquear {cidr}: incluye tu propia IP ({own_ip}).'
    net = ipaddress.ip_network(cidr)
    if not net.is_global:
        return None, f'{cidr} no es una red pública (privada, local o reservada); bloquearla rompería la red interna.'
    if net.prefixlen < MIN_BAN_PREFIX[net.version]:
        return None, f'{cidr} es un rango demasiado amplio. El máximo permitido es /{MIN_BAN_PREFIX[net.version]}.'
    allow = [r['cidr'] for r in list_allowlist(root)]
    for entry in allow:
        if net.overlaps(ipaddress.ip_network(entry)):
            return None, f'{cidr} se solapa con {entry} de la lista blanca. Quítala de ahí primero.'
    return ban(root, cidr, minutes, reason or 'Bloqueo manual', 'manual', admin_email)


def lift_ban(root, ban_id, admin_email):
    with _connect(root) as conn:
        row = conn.execute('SELECT cidr FROM ip_bans WHERE id = ?', (ban_id,)).fetchone()
        conn.execute(
            'UPDATE ip_bans SET lifted_at = ?, lifted_by = ? WHERE id = ? AND lifted_at IS NULL',
            (_iso(_now()), admin_email, ban_id),
        )
    guard_client.request_sync()
    return row['cidr'] if row else None


def _auto_ban_minutes(root, ip, rules):
    since = _iso(_now() - timedelta(days=RECIDIVE_LOOKBACK_DAYS))
    with _connect(root) as conn:
        previous = conn.execute(
            "SELECT COUNT(*) FROM ip_bans WHERE cidr = ? AND source = 'auto' AND created_at > ?",
            (parse_network(ip), since),
        ).fetchone()[0]
    return recidive_minutes(rules['sec_ban_minutes'], previous, rules), previous


def recidive_minutes(base, previous, rules):
    """Duración de un bloqueo automático tras `previous` bloqueos anteriores
    de la misma IP. Misma fórmula que usa el agente (guard/detector.py) para
    SSH, SFTP y Web: crece con el multiplicador hasta el máximo, salvo que la
    duración inicial del servicio ya sea mayor que ese máximo."""
    return min(base * (max(1, rules['sec_ban_multiplier']) ** previous),
               max(base, rules['sec_ban_max_minutes']))


def human_minutes(minutes):
    if minutes >= 1440:
        return f'{minutes // 1440} d' if minutes % 1440 == 0 else f'{minutes / 1440:.1f} d'
    if minutes >= 120:
        return f'{minutes // 60} h' if minutes % 60 == 0 else f'{minutes / 60:.1f} h'
    return f'{minutes} min'


def recidive_examples(rules, jails):
    """Tabla de ejemplo para la tarjeta de reincidencia: duración de la 1.ª
    a la 5.ª caída de una misma IP en cada servicio con los valores actuales."""
    services = [('Panel (login)', rules['sec_ban_minutes'], 'ban')]
    services += [(j['label'], j['ban_minutes'], j['mode']) for j in jails.values()]
    rows = []
    for label, base, mode in services:
        steps = [recidive_minutes(base, n, rules) for n in range(5)]
        cap = max(base, rules['sec_ban_max_minutes'])
        reached = next((i + 1 for i, m in enumerate(steps) if m >= cap), None)
        rows.append({
            'label': label, 'mode': mode, 'steps': [human_minutes(m) for m in steps],
            'cap': human_minutes(cap), 'reached': reached,
        })
    return rows


# --- registro de intentos -----------------------------------------------------

def record_attempt(root, ip, kind, email, success, user_agent=''):
    """Registra un intento de login/2FA. Si es un fallo y la IP supera el
    límite de la ventana, la bloquea. Devuelve el cidr bloqueado o None."""
    with _connect(root) as conn:
        conn.execute(
            'INSERT INTO auth_events (ts, ip, kind, email, success, user_agent) VALUES (?, ?, ?, ?, ?, ?)',
            (_iso(_now()), ip, kind, (email or '')[:254] or None, 1 if success else 0, (user_agent or '')[:300]),
        )
    if success or is_allowlisted(root, ip):
        return None
    rules = get_rules(root)
    since = _iso(_now() - timedelta(minutes=rules['sec_window_minutes']))
    with _connect(root) as conn:
        # Los fallos anteriores a un desbloqueo no cuentan dos veces.
        last_ban = conn.execute(
            'SELECT MAX(created_at) FROM ip_bans WHERE cidr = ?', (parse_network(ip),)
        ).fetchone()[0]
        start = max(since, last_ban) if last_ban else since
        failures = conn.execute(
            'SELECT COUNT(*) FROM auth_events WHERE ip = ? AND success = 0 AND ts > ?', (ip, start)
        ).fetchone()[0]
    if failures < rules['sec_max_failures'] or is_banned(root, ip):
        return None
    minutes, previous = _auto_ban_minutes(root, ip, rules)
    reason = f'{failures} intentos fallidos en {rules["sec_window_minutes"]} min'
    if previous:
        reason += f' (reincidencia #{previous + 1})'
    cidr, _ = ban(root, ip, minutes, reason, 'auto')
    panel_db.log_action(root, None, 'ip_banned_auto', f'{cidr} · {minutes} min · {reason}')
    with _connect(root) as conn:
        conn.execute('UPDATE ip_bans SET notified = 1 WHERE cidr = ? AND notified = 0', (cidr,))
    try:
        notification_control.notify(
            root, 'security_ban', 'Panel: IP bloqueada',
            f'Se bloqueó {cidr} durante {minutes} min ({reason}).',
        )
    except Exception:
        pass
    return cidr


def account_locked(root, email, ip):
    """True si la cuenta acumula demasiados fallos desde cualquier IP (ataque
    distribuido). Las IPs de la lista blanca siempre pueden intentar, para
    que un atacante no pueda dejar al admin fuera de su propio panel."""
    if not email or is_allowlisted(root, ip):
        return False
    rules = get_rules(root)
    since = _iso(_now() - timedelta(minutes=rules['sec_window_minutes']))
    with _connect(root) as conn:
        last_ok = conn.execute(
            'SELECT MAX(ts) FROM auth_events WHERE email = ? AND success = 1', (email,)
        ).fetchone()[0]
        start = max(since, last_ok) if last_ok else since
        failures = conn.execute(
            'SELECT COUNT(*) FROM auth_events WHERE email = ? AND success = 0 AND ts > ?', (email, start)
        ).fetchone()[0]
    return failures >= rules['sec_account_max_failures']


def pending_2fa_exhausted(tries):
    return tries >= _PENDING_2FA_MAX_TRIES


def list_events(root, limit=100, failures_only=False, service=None):
    clauses, params = [], []
    if failures_only:
        clauses.append('success = 0')
    if service:
        clauses.append('service = ?')
        params.append(service)
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    with _connect(root) as conn:
        rows = conn.execute(
            f'SELECT * FROM auth_events {where} ORDER BY id DESC LIMIT ?', (*params, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def notify_pending_bans(root):
    """Resumen de los bloqueos automáticos nuevos (los del servidor los crea
    el agente, que no tiene acceso a las notificaciones). Se llama desde el
    scheduler: un solo mensaje por vuelta en lugar de uno por IP."""
    with _connect(root) as conn:
        rows = conn.execute(
            "SELECT id, cidr, service, source FROM ip_bans WHERE notified = 0 ORDER BY id"
        ).fetchall()
        if not rows:
            return
        conn.execute(
            f"UPDATE ip_bans SET notified = 1 WHERE id IN ({','.join('?' for _ in rows)})",
            [r['id'] for r in rows],
        )
    # Los manuales los hizo un admin desde el panel: no hace falta avisarle.
    auto = [r for r in rows if r['source'] == 'auto']
    if not auto:
        return
    by_service = {}
    for r in auto:
        by_service.setdefault(SERVICE_LABELS.get(r['service'], r['service']), []).append(r['cidr'])
    summary_line = ', '.join(f'{svc}: {len(ips)}' for svc, ips in by_service.items())
    sample = ', '.join(r['cidr'] for r in auto[:10]) + (' …' if len(auto) > 10 else '')
    try:
        notification_control.notify(
            root, 'security_ban', f'Servidor: {len(auto)} IP(s) bloqueada(s)',
            f'Por servicio — {summary_line}.\nIPs: {sample}',
        )
    except Exception:
        pass


def summary(root):
    since = _iso(_now() - timedelta(hours=24))
    with _connect(root) as conn:
        failed = conn.execute(
            'SELECT COUNT(*) FROM auth_events WHERE success = 0 AND ts > ?', (since,)
        ).fetchone()[0]
        ok = conn.execute(
            'SELECT COUNT(*) FROM auth_events WHERE success = 1 AND ts > ?', (since,)
        ).fetchone()[0]
        top = conn.execute(
            'SELECT ip, COUNT(*) AS n FROM auth_events WHERE success = 0 AND ts > ? '
            'GROUP BY ip ORDER BY n DESC LIMIT 5',
            (since,),
        ).fetchall()
    return {
        'active_bans': len(list_active_bans(root)),
        'failed_24h': failed,
        'ok_24h': ok,
        'top_ips': [dict(r) for r in top],
    }


def prune(root):
    cutoff = _iso(_now() - timedelta(days=EVENT_RETENTION_DAYS))
    with _connect(root) as conn:
        conn.execute('DELETE FROM auth_events WHERE ts < ?', (cutoff,))


# --- gráfico de ataques -------------------------------------------------------

# Orden fijo de series (y de colores): no cambia aunque una serie quede en 0.
CHART_SERIES = [('sshd', 'SSH'), ('sftp', 'SFTP'), ('nginx', 'Web'), ('panel', 'Panel')]
_CHART_W, _CHART_H = 720, 200
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 44, 8, 10, 24
_GAP = 2


def _nice_max(value):
    if value <= 0:
        return 4
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if value <= step * magnitude:
            return int(step * magnitude) if step * magnitude >= 4 else 4
    return int(10 * magnitude)


def _top_path(x, y, w, h):
    r = min(4, h, w / 2)
    return (f'M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} '
            f'L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} L{x + w:.1f},{y + h:.1f} Z')


def attack_chart(root, hours=24):
    """Intentos fallidos por hora y servicio, ya convertidos a geometría SVG
    (barras apiladas) para dibujarlos sin librerías en la plantilla."""
    now = _now().replace(minute=0, second=0, microsecond=0)
    start = now - timedelta(hours=hours - 1)
    with _connect(root) as conn:
        rows = conn.execute(
            'SELECT substr(ts, 1, 13) AS h, service, COUNT(*) AS n FROM auth_events '
            'WHERE success = 0 AND ts >= ? GROUP BY h, service',
            (_iso(start),),
        ).fetchall()
    counts = {}
    for row in rows:
        counts.setdefault(row['h'], {})[row['service']] = row['n']
    keys = [k for k, _ in CHART_SERIES]
    buckets = []
    for i in range(hours):
        hour = start + timedelta(hours=i)
        per = counts.get(hour.strftime('%Y-%m-%dT%H'), {})
        buckets.append({
            'label': hour.strftime('%H:00'),
            'day': hour.strftime('%d/%m'),
            'counts': {k: per.get(k, 0) for k in keys},
            'total': sum(per.get(k, 0) for k in keys),
        })
    peak = max((b['total'] for b in buckets), default=0)
    y_max = _nice_max(peak)
    plot_w = _CHART_W - _PAD_L - _PAD_R
    plot_h = _CHART_H - _PAD_T - _PAD_B
    slot = plot_w / hours
    bar_w = slot * 0.64
    base_y = _PAD_T + plot_h
    for i, b in enumerate(buckets):
        x = _PAD_L + i * slot + (slot - bar_w) / 2
        b['x'], b['slot_x'], b['slot_w'] = x, _PAD_L + i * slot, slot
        segs, y = [], base_y
        present = [k for k in keys if b['counts'][k]]
        for idx, k in enumerate(present):
            h = max(2.0, b['counts'][k] / y_max * plot_h)
            if idx:
                y -= _GAP
                h = max(1.0, h - _GAP)
            y -= h
            seg = {'series': keys.index(k) + 1, 'x': x, 'y': y, 'w': bar_w, 'h': h}
            if idx == len(present) - 1:
                seg['path'] = _top_path(x, y, bar_w, h)
            segs.append(seg)
        b['segments'] = segs
    ticks = [{'value': v, 'y': base_y - v / y_max * plot_h} for v in (0, y_max // 2, y_max)]
    totals = {k: sum(b['counts'][k] for b in buckets) for k in keys}
    return {
        'width': _CHART_W, 'height': _CHART_H, 'pad_l': _PAD_L, 'pad_r': _PAD_R, 'base_y': base_y,
        'bar_w': bar_w, 'buckets': buckets, 'ticks': ticks, 'series': CHART_SERIES, 'totals': totals,
        'grand_total': sum(totals.values()),
    }


# --- tablas con buscador, orden y paginado -----------------------------------

BAN_SORTS = ('cidr', 'service', 'reason', 'source', 'created_at', 'expires_at', 'ended_at')
EVENT_SORTS = {'ts': 'ts', 'service': 'service', 'ip': 'ip', 'email': 'email', 'success': 'success'}
PAGE_SIZES = (25, 50, 100)
BAN_PAGE_SIZES = PAGE_SIZES
_FAR_FUTURE = '9999'
_SOURCE_SEARCH = {'auto': 'automático automatico', 'manual': 'manual'}


def _page_info(total, page, per_page):
    per_page = per_page if per_page in PAGE_SIZES else PAGE_SIZES[0]
    pages = max(1, -(-total // per_page))
    page = min(max(1, page), pages)
    start = (page - 1) * per_page
    return {
        'total': total, 'page': page, 'pages': pages, 'per_page': per_page, 'offset': start,
        'first': start + 1 if total else 0, 'last': min(start + per_page, total),
    }


def _ban_sort_key(field):
    if field == 'cidr':
        def key(b):
            net = ipaddress.ip_network(b['cidr'], strict=False)
            return (net.version, int(net.network_address), net.prefixlen)
        return key
    if field == 'expires_at':
        return lambda b: b['expires_at'] or _FAR_FUTURE   # permanente = el que más tarda
    if field == 'ended_at':
        return lambda b: b['lifted_at'] or b['expires_at'] or ''
    if field == 'service':
        return lambda b: SERVICE_LABELS.get(b['service'], b['service'] or '').lower()
    return lambda b: (b.get(field) or '').lower()


def _all_inactive_bans(root):
    with _connect(root) as conn:
        rows = conn.execute(
            f'SELECT * FROM ip_bans WHERE NOT ({_active_clause()})', (_iso(_now()),)
        ).fetchall()
    return [dict(r) for r in rows]


def query_bans(root, active=True, q='', sort='created_at', direction='desc', page=1, per_page=25):
    """Bloqueos (activos o el historial) filtrados, ordenados y paginados. Se
    hace en Python para poder buscar por etiqueta ("SSH", "Automático") y
    ordenar las IPs por valor numérico y no como texto."""
    sort = sort if sort in BAN_SORTS else 'created_at'
    direction = 'asc' if direction == 'asc' else 'desc'
    rows = list_active_bans(root) if active else _all_inactive_bans(root)
    total_all = len(rows)
    q = (q or '').strip().lower()[:100]
    if q:
        rows = [
            b for b in rows
            if q in ' '.join([
                b['cidr'], b['service'] or '', SERVICE_LABELS.get(b['service'], ''), b['reason'] or '',
                _SOURCE_SEARCH.get(b['source'], b['source'] or ''), b['created_by'] or '', b.get('lifted_by') or '',
            ]).lower()
        ]
    rows.sort(key=_ban_sort_key(sort), reverse=direction == 'desc')
    info = _page_info(len(rows), page, per_page)
    return {
        **info, 'items': rows[info['offset']:info['offset'] + info['per_page']],
        'total_all': total_all, 'q': q, 'sort': sort, 'direction': direction,
    }


def query_active_bans(root, **kwargs):
    return query_bans(root, active=True, **kwargs)


def query_events(root, q='', service=None, result='', sort='ts', direction='desc', page=1, per_page=25):
    """Intentos de acceso paginados en SQL: pueden ser decenas de miles."""
    column = EVENT_SORTS.get(sort, 'ts')
    sort = sort if sort in EVENT_SORTS else 'ts'
    direction = 'asc' if direction == 'asc' else 'desc'
    clauses, params = [], []
    if service in SERVICE_LABELS:
        clauses.append('service = ?')
        params.append(service)
    if result in ('ok', 'fail'):
        clauses.append('success = ?')
        params.append(1 if result == 'ok' else 0)
    q = (q or '').strip()[:100]
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        labels = [k for k, v in SERVICE_LABELS.items() if q.lower() in v.lower()]
        cond = "ip LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' OR detail LIKE ? ESCAPE '\\'"
        params += [like, like, like]
        if labels:
            cond += f" OR service IN ({','.join('?' for _ in labels)})"
            params += labels
        clauses.append(f'({cond})')
    where = ('WHERE ' + ' AND '.join(clauses)) if clauses else ''
    with _connect(root) as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM auth_events {where}', params).fetchone()[0]
        total_all = conn.execute('SELECT COUNT(*) FROM auth_events').fetchone()[0]
        info = _page_info(total, page, per_page)
        rows = conn.execute(
            f'SELECT * FROM auth_events {where} ORDER BY {column} {direction.upper()}, id {direction.upper()} '
            'LIMIT ? OFFSET ?',
            (*params, info['per_page'], info['offset']),
        ).fetchall()
    return {
        **info, 'items': [dict(r) for r in rows], 'total_all': total_all,
        'q': q, 'sort': sort, 'direction': direction, 'service': service, 'result': result,
    }
