"""Métricas de CPU, memoria y almacenamiento vía Docker API (estilo htop por proyecto)."""
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from docker_control import MANAGED_SERVICES, _container_states, _docker_request, _resolve_service_containers

# Ruta desde la que se mide el almacenamiento del host. El contenedor del portal
# monta el home del host (solo lectura) en /stack; fuera de Docker, se usa '/'.
_DISK_PATH = '/stack' if os.path.isdir('/stack') else '/'

PROJECT_LABELS = {key: meta['label'] for key, meta in MANAGED_SERVICES.items()}
PROJECT_LABELS['portal'] = 'Portal'


def _calc_cpu_percent(cpu_stats, precpu_stats):
    if not cpu_stats or not precpu_stats:
        return 0.0
    cpu_usage = cpu_stats.get('cpu_usage') or {}
    precpu_usage = precpu_stats.get('cpu_usage') or {}
    cpu_delta = cpu_usage.get('total_usage', 0) - precpu_usage.get('total_usage', 0)
    system_delta = cpu_stats.get('system_cpu_usage', 0) - precpu_stats.get('system_cpu_usage', 0)
    if system_delta <= 0 or cpu_delta < 0:
        return 0.0
    online_cpus = cpu_stats.get('online_cpus') or 1
    return (cpu_delta / system_delta) * online_cpus * 100.0


def _format_bytes(num):
    if num is None or num < 0:
        return '0 B'
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    value = float(num)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == 'B':
                return f'{int(value)} {unit}'
            return f'{value:.1f} {unit}'
        value /= 1024
    return f'{value:.1f} TB'


def _container_stats(container):
    data, err = _docker_request('GET', f'/containers/{container}/stats?stream=0', timeout=5)
    if err:
        return None, err

    memory = data.get('memory_stats') or {}
    usage = memory.get('usage', 0)
    limit = memory.get('limit', 0)
    mem_percent = (usage / limit * 100.0) if limit else 0.0

    return {
        'name': container,
        'cpu_percent': round(_calc_cpu_percent(data.get('cpu_stats'), data.get('precpu_stats')), 2),
        'memory_bytes': usage,
        'memory_limit_bytes': limit,
        'memory_percent': round(mem_percent, 2),
        'memory_human': _format_bytes(usage),
    }, ''


def _host_info():
    data, err = _docker_request('GET', '/info', timeout=5)
    if err:
        return {}, err
    return {
        'cpus': data.get('NCPU') or 1,
        'memory_total_bytes': data.get('MemTotal') or 0,
        'memory_total_human': _format_bytes(data.get('MemTotal') or 0),
    }, ''


def _host_disk_usage():
    try:
        usage = shutil.disk_usage(_DISK_PATH)
    except OSError as exc:
        return {}, f'disco: {exc}'

    used_percent = (usage.used / usage.total * 100.0) if usage.total else 0.0
    return {
        'disk_total_bytes': usage.total,
        'disk_used_bytes': usage.used,
        'disk_free_bytes': usage.free,
        'disk_total_human': _format_bytes(usage.total),
        'disk_used_human': _format_bytes(usage.used),
        'disk_free_human': _format_bytes(usage.free),
        'disk_used_percent': round(used_percent, 2),
    }, ''


def _fetch_container_stats_batch(containers):
    """Obtiene stats de varios contenedores en paralelo (cada llamada a Docker tarda ~1–2 s)."""
    if not containers:
        return {}
    workers = min(len(containers), 8)
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_container_stats, name): name for name in containers}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as exc:
                results[name] = (None, str(exc))
    return results


def get_system_metrics():
    with ThreadPoolExecutor(max_workers=3) as pool:
        states_future = pool.submit(_container_states)
        host_future = pool.submit(_host_info)
        disk_future = pool.submit(_host_disk_usage)
        states, docker_err = states_future.result()
        host, host_err = host_future.result()
        disk, disk_err = disk_future.result()

    container_to_project = {}
    for key, meta in MANAGED_SERVICES.items():
        for container in _resolve_service_containers(meta, states):
            container_to_project[container] = key
    container_to_project['portal'] = 'portal'

    projects = {}
    for key, label in PROJECT_LABELS.items():
        projects[key] = {
            'key': key,
            'label': label,
            'cpu_percent': 0.0,
            'memory_bytes': 0,
            'memory_human': '0 B',
            'containers': [],
            'running': 0,
            'total': 0,
        }

    containers_detail = []
    errors = []
    if docker_err:
        errors.append(docker_err)
    if host_err:
        errors.append(host_err)
    if disk_err:
        errors.append(disk_err)

    stats_by_container = {}
    if states:
        running_managed = [
            container
            for container, state in states.items()
            if state == 'running' and container in container_to_project
        ]
        stats_by_container = _fetch_container_stats_batch(running_managed)

        for container, state in states.items():
            project_key = container_to_project.get(container)
            if not project_key:
                continue

            entry = projects[project_key]
            entry['total'] += 1
            if state != 'running':
                entry['containers'].append({
                    'name': container,
                    'state': state,
                    'cpu_percent': 0.0,
                    'memory_bytes': 0,
                    'memory_human': '0 B',
                    'memory_percent': 0.0,
                })
                continue

            entry['running'] += 1
            stats, stat_err = stats_by_container.get(container, (None, 'sin datos'))
            if stat_err:
                errors.append(f'{container}: {stat_err}')
                entry['containers'].append({
                    'name': container,
                    'state': state,
                    'cpu_percent': 0.0,
                    'memory_bytes': 0,
                    'memory_human': '?',
                    'memory_percent': 0.0,
                })
                continue

            stats['state'] = state
            entry['cpu_percent'] += stats['cpu_percent']
            entry['memory_bytes'] += stats['memory_bytes']
            entry['containers'].append(stats)
            containers_detail.append({**stats, 'project': project_key, 'project_label': PROJECT_LABELS[project_key]})

    project_list = []
    total_cpu = 0.0
    total_mem = 0
    for key in PROJECT_LABELS:
        entry = projects[key]
        if entry['total'] == 0 and key != 'portal':
            continue
        entry['cpu_percent'] = round(entry['cpu_percent'], 2)
        entry['memory_human'] = _format_bytes(entry['memory_bytes'])
        mem_total = host.get('memory_total_bytes') or 0
        entry['memory_percent'] = round(
            (entry['memory_bytes'] / mem_total * 100.0) if mem_total else 0.0,
            2,
        )
        entry['containers'].sort(key=lambda c: c.get('memory_bytes', 0), reverse=True)
        project_list.append(entry)
        total_cpu += entry['cpu_percent']
        total_mem += entry['memory_bytes']

    project_list.sort(key=lambda p: (p['cpu_percent'], p['memory_bytes']), reverse=True)
    containers_detail.sort(key=lambda c: (c['cpu_percent'], c['memory_bytes']), reverse=True)

    mem_total = host.get('memory_total_bytes') or 0
    top = project_list[0] if project_list else None

    return {
        'host': {
            **host,
            **disk,
            'cpu_used_percent': round(total_cpu, 2),
            'memory_used_bytes': total_mem,
            'memory_used_human': _format_bytes(total_mem),
            'memory_used_percent': round((total_mem / mem_total * 100.0) if mem_total else 0.0, 2),
        },
        'projects': project_list,
        'containers': containers_detail,
        'top_project': {
            'key': top['key'],
            'label': top['label'],
            'cpu_percent': top['cpu_percent'],
            'memory_human': top['memory_human'],
        } if top else None,
        'errors': errors,
    }
