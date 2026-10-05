"""Sesiones de login abiertas en el host (SSH, consola) vía systemd-logind.

El panel no ve el host: le pide al agente la lista ("ssh_sessions") y, si el
admin lo decide, que cierre una ("ssh_terminate"). Solo se cierran sesiones
remotas de sshd, y solo por un Id que esté en la lista en ese momento: nada
de lo que llega por el socket se pasa a un comando sin validarlo.

Cerrar una sesión termina todos sus procesos, incluidos los que quedaron
vivos al desconectarse (tmux, screen, nohup): por eso la lista los muestra.
"""
import os
import re
import subprocess
from datetime import datetime, timezone

LOGINCTL = '/usr/bin/loginctl'
CGROUP_ROOT = '/sys/fs/cgroup'
_ID_RE = re.compile(r'^[A-Za-z0-9]{1,32}$')
_PROPS = ('Id', 'User', 'Name', 'Remote', 'RemoteHost', 'Service', 'TTY', 'Leader', 'Timestamp', 'Class', 'State')
_ENV = {'PATH': '/usr/bin:/bin', 'TZ': 'UTC', 'LC_ALL': 'C', 'SYSTEMD_PAGER': ''}
MAX_PROCS_SHOWN = 8


def _run(args, timeout=5):
    return subprocess.run([LOGINCTL, '--no-pager', *args], capture_output=True, text=True,
                          timeout=timeout, env=_ENV)


def _parse_ts(value):
    # Con TZ=UTC: "Mon 2026-10-05 14:14:54 UTC"
    try:
        return datetime.strptime(value, '%a %Y-%m-%d %H:%M:%S UTC').replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _processes(uid, session_id):
    """Nombres de los procesos de la sesión (desde su cgroup)."""
    path = f'{CGROUP_ROOT}/user.slice/user-{uid}.slice/session-{session_id}.scope/cgroup.procs'
    try:
        with open(path) as fh:
            pids = [p.strip() for p in fh if p.strip()]
    except OSError:
        return 0, []
    names = []
    for pid in pids:
        try:
            with open(f'/proc/{pid}/comm') as fh:
                name = fh.read().strip()
        except OSError:
            continue
        if name not in names:
            names.append(name)
    return len(pids), names[:MAX_PROCS_SHOWN]


def list_sessions():
    res = _run(['list-sessions', '--no-legend'])
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or 'loginctl list-sessions falló')
    ids = [line.split()[0] for line in res.stdout.splitlines() if line.strip()]
    sessions = []
    for sid in ids:
        if not _ID_RE.match(sid):
            continue
        res = _run(['show-session', sid, *(f'-p{p}' for p in _PROPS)])
        if res.returncode != 0:
            continue  # se cerró mientras se listaba
        info = dict(line.split('=', 1) for line in res.stdout.splitlines() if '=' in line)
        if info.get('Class') != 'user':
            continue
        uid = info.get('User', '')
        total, names = _processes(uid, sid) if uid.isdigit() else (0, [])
        remote = info.get('Remote') == 'yes'
        sessions.append({
            'id': sid,
            'user': info.get('Name', ''),
            'remote': remote,
            'host': info.get('RemoteHost', '') or None,
            'service': info.get('Service', ''),
            'tty': info.get('TTY', '') or None,
            'started_at': _parse_ts(info.get('Timestamp', '')),
            # active/online: conectada. closing: el usuario ya se fue pero
            # quedan procesos de esa sesión corriendo (tmux, screen...).
            'state': info.get('State', ''),
            'process_count': total,
            'processes': names,
            'can_terminate': remote and info.get('Service') == 'sshd',
        })
    sessions.sort(key=lambda s: s['started_at'] or '', reverse=True)
    return sessions


def terminate(session_id):
    """(ok, mensaje). Solo sesiones SSH remotas que existan ahora mismo."""
    session_id = str(session_id or '')
    if not _ID_RE.match(session_id):
        return False, 'Id de sesión no válido'
    target = next((s for s in list_sessions() if s['id'] == session_id), None)
    if target is None:
        return False, 'La sesión ya no existe'
    if not target['can_terminate']:
        return False, 'Solo se pueden cerrar sesiones SSH remotas'
    res = _run(['terminate-session', session_id], timeout=10)
    if res.returncode != 0:
        return False, res.stderr.strip() or 'loginctl terminate-session falló'
    return True, f'Sesión {session_id} de {target["user"]} ({target["host"]}) cerrada'
