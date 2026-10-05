"""Historial de accesos SSH/SFTP correctos y aviso de IPs nuevas.

Los datos los escribe stackpanel-guard en auth_events (success = 1) al leer
los logs de sshd y del contenedor SFTP; aquí solo se consultan. Las sesiones
abiertas ahora mismo no están en la base: se le piden al agente
(guard_client.ssh_sessions).

"IP nueva" = primer acceso correcto de ese usuario desde esa IP en ese
servicio dentro del periodo que se conserva (LOGIN_RETENTION_DAYS).
"""
from datetime import datetime, timedelta, timezone

import notification_control
import panel_db

SERVICES = {'sshd': 'SSH', 'sftp': 'SFTP'}
LOGIN_RETENTION_DAYS = 365
PAGE_SIZES = (25, 50, 100)
_NOTIFIED_KEY = 'ssh_login_notified_id'
_SVC_IN = "service IN ('sshd', 'sftp')"
# Primer acceso de ese usuario+IP+servicio (no hay otro correcto anterior).
_IS_NEW = (
    'NOT EXISTS (SELECT 1 FROM auth_events p WHERE p.success = 1 AND p.service = e.service '
    'AND p.ip = e.ip AND p.email IS e.email AND p.id < e.id)'
)


def _connect(root):
    return panel_db._connect(root)


def _since(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def init_db(root):
    with _connect(root) as conn:
        conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_auth_events_login '
            'ON auth_events(success, service, ip, email, id)'
        )


def summary(root):
    with _connect(root) as conn:
        row = conn.execute(
            f'SELECT '
            f'  SUM(ts > ?) AS logins_24h, '
            f'  COUNT(DISTINCT CASE WHEN ts > ? THEN ip END) AS ips_30d, '
            f'  COUNT(DISTINCT CASE WHEN ts > ? THEN email END) AS users_30d '
            f'FROM auth_events WHERE success = 1 AND {_SVC_IN}',
            (_since(hours=24), _since(days=30), _since(days=30)),
        ).fetchone()
    return {k: row[k] or 0 for k in ('logins_24h', 'ips_30d', 'users_30d')}


def query_logins(root, service=None, q='', only_new=False, page=1, per_page=25):
    clauses, params = ['e.success = 1', 'e.' + _SVC_IN], []
    if service in SERVICES:
        clauses.append('e.service = ?')
        params.append(service)
    q = (q or '').strip()[:100]
    if q:
        like = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        clauses.append("(e.ip LIKE ? ESCAPE '\\' OR e.email LIKE ? ESCAPE '\\' OR e.detail LIKE ? ESCAPE '\\')")
        params += [like, like, like]
    if only_new:
        clauses.append(_IS_NEW)
    where = ' AND '.join(clauses)
    per_page = per_page if per_page in PAGE_SIZES else PAGE_SIZES[0]
    with _connect(root) as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM auth_events e WHERE {where}', params).fetchone()[0]
        pages = max(1, -(-total // per_page))
        page = min(max(1, page), pages)
        rows = conn.execute(
            f'SELECT e.*, {_IS_NEW} AS is_new FROM auth_events e WHERE {where} '
            'ORDER BY e.id DESC LIMIT ? OFFSET ?',
            (*params, per_page, (page - 1) * per_page),
        ).fetchall()
    return {
        'items': [dict(r) for r in rows], 'total': total, 'page': page, 'pages': pages,
        'per_page': per_page, 'q': q, 'service': service, 'only_new': only_new,
    }


def known_ips(root, limit=50):
    """Desde dónde entra cada usuario: una fila por servicio+usuario+IP."""
    with _connect(root) as conn:
        rows = conn.execute(
            f'SELECT service, email AS user, ip, COUNT(*) AS logins, MIN(ts) AS first_ts, MAX(ts) AS last_ts '
            f'FROM auth_events WHERE success = 1 AND {_SVC_IN} '
            'GROUP BY service, email, ip ORDER BY last_ts DESC LIMIT ?',
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def notify_new_ips(root):
    """Avisa de accesos correctos desde una IP nueva para ese usuario. Se
    llama desde el scheduler; la primera vez solo marca hasta dónde se leyó,
    para no avisar de todo el historial de golpe."""
    last = panel_db.get_setting(root, _NOTIFIED_KEY)
    with _connect(root) as conn:
        max_id = conn.execute('SELECT COALESCE(MAX(id), 0) FROM auth_events').fetchone()[0]
        if last is None or not str(last).isdigit():
            rows = []
        else:
            rows = conn.execute(
                f'SELECT e.ts, e.service, e.email, e.ip, e.detail FROM auth_events e '
                f'WHERE e.id > ? AND e.id <= ? AND e.success = 1 AND e.{_SVC_IN} AND {_IS_NEW} '
                'ORDER BY e.id',
                (int(last), max_id),
            ).fetchall()
    panel_db.set_settings(root, {_NOTIFIED_KEY: str(max_id)})
    if not rows:
        return
    lines = [
        f'{SERVICES.get(r["service"], r["service"])} · {r["email"] or "?"} desde {r["ip"]} '
        f'({r["ts"][:16].replace("T", " ")} UTC){" · " + r["detail"] if r["detail"] else ""}'
        for r in rows[:15]
    ]
    if len(rows) > 15:
        lines.append(f'… y {len(rows) - 15} más')
    try:
        notification_control.notify(
            root, 'ssh_new_ip', f'Servidor: acceso desde {len(rows)} IP(s) nueva(s)',
            'Si no fuiste tú, revisa /admin/ssh.\n' + '\n'.join(lines),
        )
    except Exception:
        pass
