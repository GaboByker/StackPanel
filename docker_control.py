import http.client
import json
import os
import socket
import struct
import urllib.error
import urllib.request

DOCKER_SOCK = os.environ.get('DOCKER_SOCK', '/var/run/docker.sock')

MANAGED_SERVICES = {
    'social-hub': {
        'containers': ['social-hub'],
        'label': 'Social Hub',
        'database': 'html/social-hub/instance/hub.db',
        'port': 5000,
        'health_path': '/login.html',
    },
    'empires': {
        'containers': ['empires-allies'],
        'label': 'Empires & Allies',
        'database': 'html/Empires-Allies/instance/save.db',
        'port': 5006,
        'health_path': '/',
    },
    'social-empires': {
        'containers': ['social-empires'],
        'label': 'Social Empires',
        'database': 'html/social-empires/saves',
        'port': 5051,
        'health_path': '/',
    },
    'torres': {
        'containers': ['torres-db', 'torres-arquitectura'],
        'label': 'Torres Arquitectura (WordPress)',
        'database': 'html/torres-arquitectura/db-data + wp-content',
        'port': 5007,
        'health_path': '/',
        'start_order': ['torres-db', 'torres-arquitectura'],
        'stop_order': ['torres-arquitectura', 'torres-db'],
    },
    'finanzas': {
        'containers': ['finanzas-personales'],
        'label': 'Finanzas Personales',
        'database': 'html/finanzas-personales/instance/finanzas.db',
        'port': 5050,
        'health_path': '/',
    },
    'contactos': {
        'containers': ['limpieza-contactos'],
        'label': 'Limpieza de Contactos',
        'database': 'html/limpieza-contactos/instance',
        'port': 5052,
        'health_path': '/',
    },
    'wapicenter': {
        'containers': [
            'wapicenter-postgres',
            'wapicenter-redis',
            'wapicenter-api',
            'wapicenter-frontend',
        ],
        'container_prefixes': ['wapicenter-worker'],
        'compose_project': 'wapicenter',
        'label': 'WApiCenter',
        'database': 'html/WApiCenter (volumen postgres_data)',
        'port': 8090,
        'health_path': '/',
        'start_order': [
            'wapicenter-postgres',
            'wapicenter-redis',
            'wapicenter-api',
        ],
        'stop_order': [
            'wapicenter-frontend',
            'wapicenter-api',
            'wapicenter-redis',
            'wapicenter-postgres',
        ],
    },
    'gemma4': {
        'containers': ['gemma4-ollama', 'gemma4-api-manager'],
        'label': 'API Manager IA',
        'database': 'html/gemma4-api-manager/data/gemma4_manager.db',
        'port': 8070,
        'health_path': '/health',
        'start_order': ['gemma4-ollama', 'gemma4-api-manager'],
        'stop_order': ['gemma4-api-manager', 'gemma4-ollama'],
    },
    'proxy': {
        'containers': ['proxy', 'proxy-certbot'],
        'label': 'Proxy Nginx (dominios + SSL)',
        'database': 'proxy/sites (config), volumen proxy-certbot-etc (certificados)',
        'port': None,
        'health_path': '/',
        'start_order': ['proxy-certbot', 'proxy'],
        'stop_order': ['proxy', 'proxy-certbot'],
    },
    'wanqara-dashboard': {
        'containers': [
            'wanqara-dashboard-db-1',
            'wanqara-dashboard-backend-1',
            'wanqara-dashboard-frontend-1',
        ],
        'compose_project': 'wanqara-dashboard',
        'label': 'Wanqara Dashboard',
        'database': 'html/wanqara-dashboard (volumen db_data + upload_data)',
        'port': 5173,
        'health_path': '/',
        'start_order': [
            'wanqara-dashboard-db-1',
            'wanqara-dashboard-backend-1',
            'wanqara-dashboard-frontend-1',
        ],
        'stop_order': [
            'wanqara-dashboard-frontend-1',
            'wanqara-dashboard-backend-1',
            'wanqara-dashboard-db-1',
        ],
    },
}


_STOP_GRACE_SEC = 5
_STOP_HTTP_TIMEOUT = 12
_KILL_HTTP_TIMEOUT = 10


class _DockerSocketConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, connect_timeout=10):
        super().__init__('localhost')
        self._socket_path = socket_path
        self._connect_timeout = connect_timeout

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self._connect_timeout)
        self.sock.connect(self._socket_path)


def _docker_request(method, path, timeout=30):
    if not os.path.exists(DOCKER_SOCK):
        return None, f'No se encuentra el socket de Docker ({DOCKER_SOCK}).'

    conn = _DockerSocketConnection(DOCKER_SOCK)
    conn.timeout = timeout
    try:
        conn.request(method, path)
        response = conn.getresponse()
        body = response.read().decode('utf-8', errors='replace')
        if response.status >= 400:
            detail = body.strip() or response.reason
            return None, f'Docker API {response.status}: {detail}'
        if not body:
            return {}, ''
        return json.loads(body), ''
    except (TimeoutError, socket.timeout):
        return None, 'Tiempo de espera agotado al consultar Docker.'
    except OSError as exc:
        return None, f'Sin acceso a Docker: {exc}'
    except json.JSONDecodeError as exc:
        return None, f'Respuesta inválida de Docker: {exc}'
    finally:
        conn.close()


def _container_states():
    data, err = _docker_request('GET', '/containers/json?all=1')
    if err:
        return None, err

    states = {}
    for item in data:
        names = item.get('Names') or []
        for raw_name in names:
            name = raw_name.lstrip('/')
            states[name] = (item.get('State') or '').lower()
    return states, ''


def _resolve_service_containers(meta, states=None):
    """Lista todos los contenedores de un servicio, incluyendo workers escalados."""
    containers = list(meta.get('containers') or [])
    if states is None:
        states, _ = _container_states()
    if states:
        for name in states:
            for prefix in meta.get('container_prefixes') or []:
                if name.startswith(prefix) and name not in containers:
                    containers.append(name)
    return containers


def _container_running(container):
    data, err = _docker_request('GET', f'/containers/{container}/json')
    if err:
        return None, err
    state = (data.get('State') or {}).get('Status', '').lower()
    return state == 'running', state


def _is_already_stopped_error(err):
    if not err:
        return False
    lowered = err.lower()
    return (
        '404' in err
        or 'is not running' in lowered
        or 'already stopped' in lowered
    )


def _container_is_running(states, container):
    return (states or {}).get(container) == 'running'


def _stop_container(container, states=None):
    """Detiene un contenedor; omite los que ya están parados."""
    if states is not None and not _container_is_running(states, container):
        return True, ''

    _, err = _docker_request(
        'POST',
        f'/containers/{container}/stop?t={_STOP_GRACE_SEC}',
        timeout=_STOP_HTTP_TIMEOUT,
    )
    if not err or _is_already_stopped_error(err):
        return True, ''

    running, _ = _container_running(container)
    if running is False:
        return True, ''

    if running:
        _, kill_err = _docker_request(
            'POST',
            f'/containers/{container}/kill',
            timeout=_KILL_HTTP_TIMEOUT,
        )
        if not kill_err or _is_already_stopped_error(kill_err):
            return True, ''
        running, _ = _container_running(container)
        if running is False:
            return True, ''
        return False, kill_err or err

    return False, err


def _start_container(container, states=None):
    """Inicia un contenedor; omite los que ya están en marcha."""
    if states is not None and _container_is_running(states, container):
        return True, ''

    _, err = _docker_request('POST', f'/containers/{container}/start', timeout=15)
    if not err:
        return True, ''
    if '404' in err:
        return False, err
    lowered = err.lower()
    if 'already started' in lowered or 'is not paused' in lowered:
        return True, ''
    return False, err


def _health_check(container, port, path='/'):
    url = f'http://{container}:{port}{path}'
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return response.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except OSError:
        return False


def list_service_status():
    states, docker_err = _container_states()
    result = []
    for key, meta in MANAGED_SERVICES.items():
        containers = _resolve_service_containers(meta, states)
        primary = containers[0] if containers else ''
        running = False
        state = 'unknown'
        error = docker_err
        container_states = []

        if states is not None:
            for container in containers:
                cstate = states.get(container, 'missing')
                container_states.append({'name': container, 'state': cstate})
            if container_states:
                running_count = sum(1 for c in container_states if c['state'] == 'running')
                if running_count == len(container_states):
                    running = True
                    state = 'running'
                elif running_count > 0:
                    running = False
                    state = f'parcial ({running_count}/{len(container_states)})'
                else:
                    first = container_states[0]['state']
                    state = first if first != 'missing' else 'stopped'
                    running = False
        else:
            inspected, inspect_state = _container_running(primary)
            if inspected is not None:
                running = inspected
                state = inspect_state or ('running' if running else 'stopped')
                error = ''
            elif meta.get('port'):
                if _health_check(primary, meta['port'], meta.get('health_path', '/')):
                    running = True
                    state = 'running (red)'
                    error = docker_err or 'Estado inferido por red; Docker no respondió.'

        result.append({
            'key': key,
            'label': meta['label'],
            'container': primary,
            'containers': containers,
            'container_states': container_states,
            'database': meta['database'],
            'port': meta.get('port'),
            'running': running,
            'state': state,
            'error': error,
        })
    return result


def stop_service(service_key):
    meta = MANAGED_SERVICES.get(service_key)
    if not meta:
        return False, 'Servicio desconocido.'

    states, docker_err = _container_states()
    if docker_err:
        return False, docker_err

    containers = _resolve_service_containers(meta, states)
    stop_order = meta.get('stop_order') or list(reversed(containers))
    ordered = [c for c in stop_order if c in containers]
    ordered.extend(c for c in containers if c not in ordered)

    stopped = []
    skipped = []
    for container in ordered:
        if not _container_is_running(states, container):
            skipped.append(container)
            continue
        ok, err = _stop_container(container, states)
        if not ok:
            return False, err
        stopped.append(container)
        states[container] = 'exited'

    if not stopped and skipped:
        return True, 'El proyecto ya estaba detenido.'

    parts = []
    if stopped:
        parts.append('detenidos: ' + ', '.join(stopped))
    if skipped:
        parts.append('ya parados: ' + ', '.join(skipped))
    return True, 'Contenedores ' + '; '.join(parts) + '.'


def start_service(service_key):
    meta = MANAGED_SERVICES.get(service_key)
    if not meta:
        return False, 'Servicio desconocido.'

    states, docker_err = _container_states()
    if docker_err:
        return False, docker_err

    containers = _resolve_service_containers(meta, states)
    start_order = meta.get('start_order') or containers
    ordered = [c for c in start_order if c in containers]
    ordered.extend(c for c in containers if c not in ordered)

    started = []
    skipped = []
    for container in ordered:
        if _container_is_running(states, container):
            skipped.append(container)
            continue
        ok, err = _start_container(container, states)
        if not ok:
            return False, err
        started.append(container)
        states[container] = 'running'

    if not started and skipped:
        return True, 'El proyecto ya estaba en marcha.'

    parts = []
    if started:
        parts.append('iniciados: ' + ', '.join(started))
    if skipped:
        parts.append('ya en marcha: ' + ', '.join(skipped))
    return True, 'Contenedores ' + '; '.join(parts) + '.'


def container_logs(container, tail=200):
    """Últimas líneas de stdout/stderr de un contenedor (para verlas desde el
    panel). No usa _docker_request porque esa espera JSON y esto es un
    stream de texto multiplexado."""
    if not os.path.exists(DOCKER_SOCK):
        return None, f'No se encuentra el socket de Docker ({DOCKER_SOCK}).'
    conn = _DockerSocketConnection(DOCKER_SOCK)
    conn.timeout = 20
    try:
        conn.request(
            'GET', f'/containers/{container}/logs?stdout=1&stderr=1&timestamps=1&tail={int(tail)}'
        )
        response = conn.getresponse()
        raw = response.read()
        if response.status >= 400:
            return None, raw.decode('utf-8', errors='replace')
    except (TimeoutError, socket.timeout) as exc:
        return None, f'Tiempo de espera agotado: {exc}'
    except OSError as exc:
        return None, f'Sin acceso a Docker: {exc}'
    finally:
        conn.close()

    chunks = []
    i = 0
    while i + 8 <= len(raw):
        length = struct.unpack('>I', raw[i + 4:i + 8])[0]
        start = i + 8
        end = start + length
        chunks.append(raw[start:end])
        i = end
    text = b''.join(chunks).decode('utf-8', errors='replace') if chunks else raw.decode('utf-8', errors='replace')
    return text, ''


def list_all_containers():
    """Lista cruda de todos los contenedores (nombre, estado, labels de
    compose, puertos publicados), usado para detectar proyectos ya
    corriendo que aún no están registrados en el panel."""
    data, err = _docker_request('GET', '/containers/json?all=1')
    if err or data is None:
        return [], err
    result = []
    for item in data:
        names = [n.lstrip('/') for n in (item.get('Names') or [])]
        ports = item.get('Ports') or []
        host_ports = sorted({p['PublicPort'] for p in ports if p.get('PublicPort')})
        result.append({
            'name': names[0] if names else '',
            'names': names,
            'state': (item.get('State') or '').lower(),
            'labels': item.get('Labels') or {},
            'host_ports': host_ports,
        })
    return result, ''


def containers_status(containers):
    """Estado simple {running, states} para una lista arbitraria de contenedores
    (usado por proyectos registrados manualmente, fuera de MANAGED_SERVICES)."""
    states, err = _container_states()
    if err or states is None:
        return {'running': False, 'state': 'desconocido', 'error': err}
    found = [{'name': c, 'state': states.get(c, 'missing')} for c in containers]
    if not found:
        return {'running': False, 'state': 'sin contenedores', 'error': ''}
    running_count = sum(1 for c in found if c['state'] == 'running')
    if running_count == len(found):
        state = 'running'
    elif running_count > 0:
        state = f'parcial ({running_count}/{len(found)})'
    else:
        first = found[0]['state']
        state = first if first != 'missing' else 'stopped'
    return {'running': running_count == len(found) and len(found) > 0, 'state': state, 'containers': found, 'error': ''}


def stop_containers(containers):
    states, err = _container_states()
    if err:
        return False, err
    stopped = []
    for container in containers:
        if not _container_is_running(states, container):
            continue
        ok, err = _stop_container(container, states)
        if not ok:
            return False, err
        stopped.append(container)
    return True, ', '.join(stopped) if stopped else 'ya estaba detenido'


def start_containers(containers):
    states, err = _container_states()
    if err:
        return False, err
    started = []
    for container in containers:
        if _container_is_running(states, container):
            continue
        ok, err = _start_container(container, states)
        if not ok:
            return False, err
        started.append(container)
    return True, ', '.join(started) if started else 'ya estaba en marcha'


def container_to_project_map():
    """Mapea nombre de contenedor -> clave de proyecto."""
    mapping = {}
    states, _ = _container_states()
    for key, meta in MANAGED_SERVICES.items():
        for container in _resolve_service_containers(meta, states):
            mapping[container] = key
    mapping['portal'] = 'portal'
    return mapping
