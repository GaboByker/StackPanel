"""Hilo de fondo del panel: muestreo de métricas cada 5 min, revisión de
salud/disco/SSL con notificaciones, y backups automáticos con retención.
Se inicia una sola vez al arrancar portal-server.py."""
import os
import socket
import ssl
import threading
import time
from datetime import datetime, timezone

import backup_control
import docker_control
import notification_control
import panel_db
from system_monitor import get_system_metrics

_STARTED = False
_TICK_SECONDS = 300


def start(root, stack_root, backups_dir):
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    thread = threading.Thread(target=_loop, args=(root, stack_root, backups_dir), daemon=True)
    thread.start()


def _loop(root, stack_root, backups_dir):
    alert_if_down = False  # primera vuelta: solo aprende el estado real, no alarma
    tick = 0
    while True:
        try:
            _sample_metrics(root)
            _check_health(root, alert_if_down)
            alert_if_down = True
            if tick % 6 == 0:
                _check_disk(root)
                _check_ssl(root)
            _run_scheduled_backups(root, stack_root, backups_dir)
        except Exception:
            pass
        tick += 1
        time.sleep(_TICK_SECONDS)


def _sample_metrics(root):
    host = (get_system_metrics() or {}).get('host', {})
    panel_db.add_metrics_sample(
        root, host.get('cpu_used_percent'), host.get('memory_used_percent'), host.get('disk_used_percent'),
    )


def _check_health(root, alert_if_down):
    projects = [p for p in panel_db.list_projects_raw(root) if p.get('monitor_health') and p.get('containers')]
    if not projects:
        return
    states, err = docker_control._container_states()
    if err or states is None:
        return
    for project in projects:
        containers = panel_db.project_containers(project)
        if not containers:
            continue
        running = any(states.get(c) == 'running' for c in containers)
        if project.get('desired_state', 'running') == 'running' and not running and alert_if_down:
            notification_control.notify(
                root, 'project_down',
                f"Proyecto caído: {project['name']}",
                f"\"{project['name']}\" debería estar corriendo pero ninguno de sus contenedores "
                f"lo está ({', '.join(containers)}).",
            )


def _check_disk(root):
    pct = (get_system_metrics() or {}).get('host', {}).get('disk_used_percent') or 0
    if pct >= 90:
        notification_control.notify(
            root, 'disk_full', 'Disco casi lleno', f'El disco del servidor está al {pct:.1f}% de uso.',
        )


def _check_ssl(root):
    for site in panel_db.list_sites(root):
        domain = site['domain']
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((domain, 443), timeout=8) as sock:
                with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert()
            expires = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
            days_left = (expires - datetime.utcnow()).days
            if days_left <= 14:
                notification_control.notify(
                    root, 'ssl_expiring', f'Certificado SSL de {domain} por vencer',
                    f'Quedan {days_left} días antes de que expire.',
                )
        except Exception:
            continue


def _run_scheduled_backups(root, stack_root, backups_dir):
    """Cada proyecto tiene su propio día(s) de la semana + hora + retención
    (ver panel_db.set_backup_schedule). No hay un horario compartido: cada
    uno corre cuando el admin lo configuró para ESE proyecto."""
    now = datetime.now()
    weekday = str(now.weekday())  # 0=lunes ... 6=domingo
    today = now.date().isoformat()
    os.makedirs(backups_dir, exist_ok=True)

    for project in panel_db.list_projects_raw(root):
        if not project.get('auto_backup'):
            continue
        days = (project.get('backup_days') or '').split(',')
        if weekday not in days:
            continue
        if now.hour != (project.get('backup_hour') if project.get('backup_hour') is not None else 3):
            continue
        if project.get('last_auto_backup_date') == today:
            continue

        folder_abs = os.path.join(stack_root, project['folder']) if project.get('folder') else None
        volumes = panel_db.project_volumes(project)
        if not (folder_abs and os.path.isdir(folder_abs)) and not volumes:
            continue
        try:
            data = backup_control.build_backup(folder_abs, volumes)
        except Exception:
            continue
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        with open(os.path.join(backups_dir, f"{project['project_key']}-{stamp}.tar.gz"), 'wb') as fh:
            fh.write(data)
        _prune_backups(backups_dir, project['project_key'], project.get('backup_retention') or 7)
        panel_db.set_last_auto_backup_date(root, project['id'], today)


def _prune_backups(backups_dir, project_key, retention):
    files = sorted(
        (f for f in os.listdir(backups_dir) if f.startswith(project_key + '-')),
        reverse=True,
    )
    for old in files[retention:]:
        try:
            os.remove(os.path.join(backups_dir, old))
        except OSError:
            pass
