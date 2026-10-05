"""Motor de detección de stackpanel-guard (reemplazo de fail2ban).

Lee en vivo los logs de cada servicio ("jail"), reconoce intentos de acceso
fallidos y, cuando una IP supera el límite de su jail dentro de la ventana,
registra el bloqueo en la base del panel. El propio agente lo lleva luego al
kernel, igual que un bloqueo hecho a mano.

Jails:
  sshd   SSH del servidor          journald (SYSLOG_IDENTIFIER sshd/sshd-session)
  sftp   SFTP de los proyectos      logs del contenedor stackpanel-sftp
  nginx  Webs a través del proxy    access log del contenedor del proxy

Cada jail tiene tres modos, configurables desde el panel:
  off      no lee ese log
  observe  registra los intentos y avisa de quién se habría bloqueado
  ban      además bloquea

La configuración vive en la base (settings.sec_jails, JSON); este archivo
solo trae los valores por defecto. Nada de lo que llega en un log se
ejecuta: cada IP pasa por ipaddress antes de usarse.
"""
import collections
import ipaddress
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger('stackpanel-guard.detector')

JAIL_DEFAULTS = {
    'sshd': {'mode': 'ban', 'max_failures': 5, 'window_minutes': 10, 'ban_minutes': 60},
    'sftp': {'mode': 'ban', 'max_failures': 5, 'window_minutes': 10, 'ban_minutes': 60,
             'container': 'stackpanel-sftp'},
    'nginx': {'mode': 'observe', 'max_failures': 10, 'window_minutes': 10, 'ban_minutes': 1440,
              'container': 'proxy'},
}
GLOBAL_DEFAULTS = {'sec_ban_multiplier': 2, 'sec_ban_max_minutes': 10080}
RECIDIVE_LOOKBACK_DAYS = 30
STATE_FILE = '/var/lib/stackpanel-guard/state.json'
DOCKER = '/usr/bin/docker'
JOURNALCTL = '/usr/bin/journalctl'

# --- reconocimiento de líneas -------------------------------------------------

_IP = r'(?P<ip>[0-9A-Fa-f:.]+)'
_PORT = r'port (?P<port>\d+)'

# Fallo "duro": un intento real de credencial. Cuenta siempre.
SSH_FAIL = [
    re.compile(rf'^Failed (?P<method>password|publickey|keyboard-interactive/pam) for (?:invalid user )?(?P<user>\S*) from {_IP} {_PORT}'),
]
# Fallo "blando": sondeos sin credencial o el cierre de una conexión ya
# fallida. Cuenta una sola vez por conexión (IP+puerto de origen), para que
# una misma conexión no sume 3 veces ("Invalid user" + "Failed" + "closed").
SSH_SOFT = [
    re.compile(rf'^Invalid user (?P<user>\S*) from {_IP} {_PORT}'),
    re.compile(rf'^Failed none for (?:invalid user )?(?P<user>\S*) from {_IP} {_PORT}'),
    re.compile(rf'^(?:Connection closed|Disconnected|Connection reset) by (?:authenticating|invalid) user (?P<user>\S*) {_IP} {_PORT}'),
    re.compile(rf'^Unable to negotiate with {_IP} {_PORT}'),
    re.compile(rf'^banner exchange: Connection from {_IP} {_PORT}: invalid format'),
    re.compile(rf'^(?:error: )?maximum authentication attempts exceeded for (?:invalid user )?(?P<user>\S*) from {_IP} {_PORT}'),
]
SSH_OK = re.compile(rf'^Accepted (?P<method>\S+) for (?P<user>\S+) from {_IP} {_PORT}')

NGINX_LINE = re.compile(r'^(?P<ip>\S+) \S+ \S+ \[[^\]]+\] "(?P<req>[^"]*)" (?P<status>\d{3}) ')
NGINX_METHODS = {'GET', 'POST', 'HEAD', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'}
# Rutas que solo pide quien está buscando vulnerabilidades.
NGINX_SCAN = re.compile(
    r'(?i)(/\.env|/\.git|/\.aws|/\.docker|/\.vscode|/\.idea|/\.ht|/\.ssh|phpinfo\.php|shell\.php|cmd\.php'
    r'|eval-stdin\.php|/vendor/phpunit|/boaform|/cgi-bin/|%2e%2e|\.\./|\.%2e|%%32%65|/phpmyadmin|/pma/'
    r'|/HNAP1|/actuator/|/wp-config\.php|/setup\.cgi|/GponForm|/\.DS_Store|/config\.json$|/server-status)'
)
NGINX_IGNORE = re.compile(r'^/\.well-known/acme-challenge/')


def parse_ssh(message):
    """-> (resultado, ip, puerto, usuario, detalle) o None.
    resultado: 'fail' | 'soft' | 'ok'."""
    m = SSH_OK.match(message)
    if m:
        return 'ok', m['ip'], m['port'], m['user'], f'Acceso con {m["method"]}'
    for rx in SSH_FAIL:
        m = rx.match(message)
        if m:
            return 'fail', m['ip'], m['port'], m.groupdict().get('user'), f'Contraseña/clave incorrecta ({m["method"]})'
    for rx in SSH_SOFT:
        m = rx.match(message)
        if m:
            return 'soft', m['ip'], m['port'], m.groupdict().get('user'), message[:160]
    return None


def parse_nginx(line):
    """-> ('fail', ip, None, None, detalle) para una petición maliciosa, o None."""
    m = NGINX_LINE.match(line)
    if not m:
        return None
    req, status = m['req'], int(m['status'])
    parts = req.split(' ')
    method = parts[0] if parts else ''
    path = parts[1] if len(parts) > 1 else ''
    if NGINX_IGNORE.match(path):
        return None
    bad = (
        status in (400, 444)
        or method == 'CONNECT'
        or (req and method not in NGINX_METHODS and method != 'CONNECT')
        or bool(NGINX_SCAN.search(path))
    )
    if not bad:
        return None
    return 'fail', m['ip'], None, None, f'{status} {req[:150]}'


# --- configuración ------------------------------------------------------------

def load_jails(conn):
    """Configuración efectiva de cada jail: defaults + lo guardado en el panel."""
    jails = {k: dict(v) for k, v in JAIL_DEFAULTS.items()}
    globals_ = dict(GLOBAL_DEFAULTS)
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE key IN ('sec_jails', 'sec_ban_multiplier', 'sec_ban_max_minutes')"
    ).fetchall()
    for key, value in rows:
        if key == 'sec_jails':
            try:
                stored = json.loads(value or '{}')
            except ValueError:
                stored = {}
            for name, conf in stored.items():
                if name in jails and isinstance(conf, dict):
                    jails[name].update({k: v for k, v in conf.items() if k in jails[name]})
        else:
            try:
                globals_[key] = int(value)
            except (TypeError, ValueError):
                pass
    for name, conf in jails.items():
        if conf.get('mode') not in ('off', 'observe', 'ban'):
            conf['mode'] = JAIL_DEFAULTS[name]['mode']
        for num in ('max_failures', 'window_minutes', 'ban_minutes'):
            try:
                conf[num] = max(1, int(conf[num]))
            except (TypeError, ValueError):
                conf[num] = JAIL_DEFAULTS[name][num]
        if 'container' in conf and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', str(conf['container'])):
            conf['container'] = JAIL_DEFAULTS[name]['container']
    return jails, globals_


# --- lectores de logs ---------------------------------------------------------

class Reader(threading.Thread):
    """Sigue un log con un proceso hijo (journalctl -f / docker logs -f) y
    lo relanza si termina (p. ej. el contenedor SFTP se recrea al cambiar
    un acceso). Cada línea va a detector.handle()."""

    def __init__(self, detector, jail):
        super().__init__(daemon=True, name=f'reader-{jail}')
        self.detector = detector
        self.jail = jail
        self.proc = None
        self.stop_flag = threading.Event()
        self.info = {'running': False, 'lines': 0, 'last_line_at': None, 'error': None, 'source': ''}

    def command(self):
        raise NotImplementedError

    def handle_line(self, raw):
        raise NotImplementedError

    def run(self):
        while not self.stop_flag.is_set():
            cmd = self.command()
            if cmd is None:
                self.stop_flag.wait(15)
                continue
            try:
                self.proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    errors='replace', env={'DOCKER_CONFIG': '/tmp/stackpanel-guard-docker', 'PATH': '/usr/bin:/bin'},
                )
                self.info.update(running=True, error=None)
                for raw in self.proc.stdout:
                    if self.stop_flag.is_set():
                        break
                    self.info['lines'] += 1
                    self.info['last_line_at'] = datetime.now(timezone.utc).isoformat()
                    try:
                        self.handle_line(raw.rstrip('\n'))
                    except Exception as exc:  # una línea rara nunca tumba el lector
                        log.debug('línea ignorada en %s: %s', self.jail, exc)
                self.proc.wait()
                if not self.stop_flag.is_set():
                    self.info['error'] = f'el proceso de lectura terminó (código {self.proc.returncode}); reintentando'
            except Exception as exc:
                self.info['error'] = str(exc)
            self.info['running'] = False
            self.stop_flag.wait(10)

    def stop(self):
        self.stop_flag.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class JournalReader(Reader):
    def command(self):
        cursor = self.detector.state.get('journal_cursor')
        self.info['source'] = 'journald: sshd'
        cmd = [JOURNALCTL, '-f', '-o', 'json', '-t', 'sshd', '-t', 'sshd-session', '--no-pager']
        return cmd + (['--after-cursor', cursor] if cursor else ['-n', '0'])

    def handle_line(self, raw):
        if not raw.startswith('{'):
            return
        entry = json.loads(raw)
        self.detector.state['journal_cursor'] = entry.get('__CURSOR')
        message = entry.get('MESSAGE')
        if not isinstance(message, str):
            return
        ts = datetime.fromtimestamp(int(entry['__REALTIME_TIMESTAMP']) / 1e6, timezone.utc)
        parsed = parse_ssh(message)
        if parsed:
            self.detector.handle(self.jail, ts, *parsed)


class DockerReader(Reader):
    def __init__(self, detector, jail, parser):
        super().__init__(detector, jail)
        self.parser = parser

    def command(self):
        container = self.detector.jails[self.jail].get('container')
        self.info['source'] = f'contenedor: {container}'
        exists = subprocess.run(
            [DOCKER, 'inspect', '--format', '{{.Id}}', container], capture_output=True, text=True,
            env={'DOCKER_CONFIG': '/tmp/stackpanel-guard-docker', 'PATH': '/usr/bin:/bin'},
        )
        if exists.returncode != 0:
            self.info['error'] = f'el contenedor "{container}" no existe (se reintenta)'
            return None
        since = self.detector.state.setdefault('docker_since', {}).get(self.jail)
        if not since:
            since = datetime.now(timezone.utc).isoformat()
        return [DOCKER, 'logs', '-f', '--timestamps', '--since', since, container]

    def handle_line(self, raw):
        stamp, _, line = raw.partition(' ')
        try:
            ts = datetime.fromisoformat(stamp[:26].rstrip('Z') + '+00:00') if stamp else None
        except ValueError:
            return
        if ts is None:
            return
        # +1 µs para no reprocesar la última línea al relanzar `docker logs`.
        self.detector.state.setdefault('docker_since', {})[self.jail] = (ts + timedelta(microseconds=1)).isoformat()
        parsed = self.parser(line)
        if parsed:
            self.detector.handle(self.jail, ts, *parsed)


# --- detector -----------------------------------------------------------------

class Detector:
    def __init__(self, guard):
        self.guard = guard
        self.lock = threading.Lock()
        self.jails = {k: dict(v) for k, v in JAIL_DEFAULTS.items()}
        self.globals = dict(GLOBAL_DEFAULTS)
        self.readers = {}
        self.windows = collections.defaultdict(collections.deque)   # (jail, ip) -> timestamps
        self.counted_conns = collections.OrderedDict()               # (jail, ip, port) -> None
        self.observed = {}                                           # (jail, ip) -> último aviso
        self.pending_events = []
        self.pending_bans = []
        self.state = self._load_state()
        self.stats = collections.defaultdict(lambda: {'failures': 0, 'bans': 0, 'observed': 0})

    # estado persistente (posición en cada log) -------------------------------
    def _load_state(self):
        try:
            with open(STATE_FILE) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            tmp = STATE_FILE + '.tmp'
            with open(tmp, 'w') as fh:
                json.dump(self.state, fh)
            os.replace(tmp, STATE_FILE)
        except OSError as exc:
            log.warning('no se pudo guardar el estado: %s', exc)

    # configuración -----------------------------------------------------------
    def configure(self, jails, globals_):
        with self.lock:
            changed_container = {
                name for name in ('sftp', 'nginx')
                if jails[name].get('container') != self.jails[name].get('container')
            }
            self.jails, self.globals = jails, globals_
        for name, conf in jails.items():
            reader = self.readers.get(name)
            want = conf['mode'] != 'off'
            if reader and (not want or name in changed_container):
                reader.stop()
                self.readers.pop(name)
                if name in changed_container:
                    self.state.get('docker_since', {}).pop(name, None)
                reader = None
            if want and reader is None:
                if name == 'sshd':
                    reader = JournalReader(self, name)
                elif name == 'sftp':
                    reader = DockerReader(self, name, parse_ssh)
                else:
                    reader = DockerReader(self, name, parse_nginx)
                self.readers[name] = reader
                reader.start()
                log.info('jail %s activa en modo %s', name, conf['mode'])

    # eventos -----------------------------------------------------------------
    def handle(self, jail, ts, result, ip, port, user, detail):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return
        if not addr.is_global:
            return
        ip = str(addr)
        with self.lock:
            conf = self.jails.get(jail)
            if not conf or conf['mode'] == 'off':
                return
            if result == 'soft':
                key = (jail, ip, port)
                if key in self.counted_conns:
                    return
            if result in ('fail', 'soft') and port:
                self.counted_conns[(jail, ip, port)] = None
                while len(self.counted_conns) > 20000:
                    self.counted_conns.popitem(last=False)
            success = result == 'ok'
            self.pending_events.append((ts.isoformat(), ip, jail, 'ssh' if jail != 'nginx' else 'http',
                                        (user or None), 1 if success else 0, detail))
            if success or self.guard.is_allowed(ip) or self.guard.is_banned(ip):
                return
            self.stats[jail]['failures'] += 1
            window = self.windows[(jail, ip)]
            window.append(ts)
            limit = ts - timedelta(minutes=conf['window_minutes'])
            while window and window[0] < limit:
                window.popleft()
            if len(window) < conf['max_failures']:
                return
            count = len(window)
            window.clear()
            if conf['mode'] == 'observe':
                last = self.observed.get((jail, ip))
                if last and ts - last < timedelta(minutes=conf['window_minutes']):
                    return
                self.observed[(jail, ip)] = ts
                self.stats[jail]['observed'] += 1
                self.pending_bans.append((ip, jail, count, conf, True))
                return
            self.stats[jail]['bans'] += 1
            self.pending_bans.append((ip, jail, count, conf, False))
            # Hasta que el bloqueo llegue al kernel (segundos), que la misma
            # IP no genere otro bloqueo duplicado.
            self.guard.mark_banned(ip)

    def flush(self, db_path):
        """Escribe en la base los eventos y bloqueos acumulados. Devuelve
        True si hubo bloqueos nuevos (para aplicarlos al kernel ya)."""
        with self.lock:
            events, self.pending_events = self.pending_events, []
            bans, self.pending_bans = self.pending_bans, []
        if not events and not bans:
            return False
        now = datetime.now(timezone.utc)
        conn = sqlite3.connect(db_path, timeout=15)
        try:
            cols = {r[1] for r in conn.execute('PRAGMA table_info(auth_events)')}
            if 'detail' in cols:
                conn.executemany(
                    'INSERT INTO auth_events (ts, ip, service, kind, email, success, detail) VALUES (?, ?, ?, ?, ?, ?, ?)',
                    events,
                )
            else:  # panel sin actualizar todavía
                conn.executemany(
                    'INSERT INTO auth_events (ts, ip, service, kind, email, success) VALUES (?, ?, ?, ?, ?, ?)',
                    [e[:6] for e in events],
                )
            new_ban = False
            for ip, jail, count, conf, observe_only in bans:
                cidr = str(ipaddress.ip_network(ip))
                reason = f'{count} intentos fallidos en {conf["window_minutes"]} min'
                if observe_only:
                    conn.execute(
                        'INSERT INTO audit_log (ts, admin_email, action, detail) VALUES (?, NULL, ?, ?)',
                        (now.isoformat(), 'jail_observe', f'{jail} · {cidr} · {reason} (modo observar: no se bloqueó)'),
                    )
                    continue
                since = (now - timedelta(days=RECIDIVE_LOOKBACK_DAYS)).isoformat()
                previous = conn.execute(
                    "SELECT COUNT(*) FROM ip_bans WHERE cidr = ? AND source = 'auto' AND created_at > ?",
                    (cidr, since),
                ).fetchone()[0]
                minutes = min(
                    conf['ban_minutes'] * (max(1, self.globals['sec_ban_multiplier']) ** previous),
                    max(conf['ban_minutes'], self.globals['sec_ban_max_minutes']),
                )
                if previous:
                    reason += f' (reincidencia #{previous + 1})'
                conn.execute(
                    'INSERT INTO ip_bans (cidr, service, source, reason, created_at, expires_at, created_by) '
                    "VALUES (?, ?, 'auto', ?, ?, ?, 'stackpanel-guard')",
                    (cidr, jail, reason, now.isoformat(), (now + timedelta(minutes=minutes)).isoformat()),
                )
                conn.execute(
                    'INSERT INTO audit_log (ts, admin_email, action, detail) VALUES (?, NULL, ?, ?)',
                    (now.isoformat(), 'ip_banned_auto', f'{cidr} · {minutes} min · {jail}: {reason}'),
                )
                log.info('bloqueo %s: %s durante %s min (%s)', jail, cidr, minutes, reason)
                new_ban = True
            conn.commit()
        except sqlite3.Error:
            # Se reintentan en el siguiente ciclo.
            with self.lock:
                self.pending_events = events + self.pending_events
                self.pending_bans = bans + self.pending_bans
            raise
        finally:
            conn.close()
        return new_ban

    def status(self):
        with self.lock:
            return {
                name: {
                    'config': self.jails[name],
                    'reader': dict(self.readers[name].info) if name in self.readers else None,
                    'since_start': dict(self.stats[name]),
                }
                for name in self.jails
            }
