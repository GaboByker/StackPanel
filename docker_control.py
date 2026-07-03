import http.client
import json
import os
import socket
import urllib.error
import urllib.request

DOCKER_SOCK = os.environ.get('DOCKER_SOCK', '/var/run/docker.sock')

MANAGED_SERVICES = {
    'empires': {
        'container': 'empires-allies',
        'label': 'Empires & Allies',
        'database': 'Empires-Allies/instance/save.db',
        'port': 5006,
        'health_path': '/',
    },
    'finanzas': {
        'container': 'finanzas-personales',
        'label': 'Finanzas Personales',
        'database': 'finanzas-personales/instance/finanzas.db',
        'port': 5050,
        'health_path': '/',
    },
}


class _DockerSocketConnection(http.client.HTTPConnection):
    def __init__(self, socket_path):
        super().__init__('localhost')
        self._socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(30)
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


def _container_running(container):
    data, err = _docker_request('GET', f'/containers/{container}/json')
    if err:
        return None, err
    state = (data.get('State') or {}).get('Status', '').lower()
    return state == 'running', state


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
        container = meta['container']
        running = False
        state = 'unknown'
        error = docker_err

        if states is not None:
            state = states.get(container, 'missing')
            running = state == 'running'
        else:
            inspected, inspect_state = _container_running(container)
            if inspected is not None:
                running = inspected
                state = inspect_state or ('running' if running else 'stopped')
                error = ''
            elif meta.get('port'):
                if _health_check(container, meta['port'], meta.get('health_path', '/')):
                    running = True
                    state = 'running (red)'
                    error = docker_err or 'Estado inferido por red; Docker no respondió.'

        result.append({
            'key': key,
            'label': meta['label'],
            'container': container,
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
    container = meta['container']
    _, err = _docker_request('POST', f'/containers/{container}/stop?t=30')
    if err:
        return False, err
    return True, f'Contenedor {container} detenido.'


def start_service(service_key):
    meta = MANAGED_SERVICES.get(service_key)
    if not meta:
        return False, 'Servicio desconocido.'
    container = meta['container']
    _, err = _docker_request('POST', f'/containers/{container}/start')
    if err:
        return False, err
    return True, f'Contenedor {container} iniciado.'
