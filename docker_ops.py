"""Primitivas Docker de bajo nivel (crear red/volumen/contenedor, pull de
imagen, exportar/importar volúmenes como tar) habladas directo por el
socket de Docker. Usado por el instalador de apps de 1 clic y por backups."""
import json
import os
import socket

DOCKER_SOCK = os.environ.get('DOCKER_SOCK', '/var/run/docker.sock')


def _conn(timeout=30):
    import http.client

    class Conn(http.client.HTTPConnection):
        def __init__(self):
            super().__init__('localhost')
            self.timeout = timeout

        def connect(self):
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect(DOCKER_SOCK)

    return Conn()


def request(method, path, body=None, raw_body=None, timeout=30, headers=None):
    """Devuelve (status, bytes). body=dict -> JSON; raw_body=bytes -> tal cual."""
    conn = _conn(timeout)
    try:
        data = raw_body
        hdrs = dict(headers or {})
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            hdrs['Content-Type'] = 'application/json'
        elif raw_body is not None:
            hdrs.setdefault('Content-Type', 'application/x-tar')
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def ensure_network(name):
    status, raw = request('GET', f'/networks/{name}')
    if status == 200:
        return True, ''
    status, raw = request('POST', '/networks/create', body={'Name': name, 'Driver': 'bridge'})
    if status not in (201,):
        return False, raw.decode('utf-8', errors='replace')
    return True, ''


def ensure_volume(name):
    status, raw = request('POST', '/volumes/create', body={'Name': name})
    if status not in (201,):
        return False, raw.decode('utf-8', errors='replace')
    return True, ''


def image_exists(image):
    status, _ = request('GET', f'/images/{image}/json')
    return status == 200


def pull_image(image):
    if ':' in image:
        repo, tag = image.rsplit(':', 1)
    else:
        repo, tag = image, 'latest'
    status, raw = request('POST', f'/images/create?fromImage={repo}&tag={tag}', body=None, timeout=600)
    if status >= 400:
        return False, raw.decode('utf-8', errors='replace')
    # Revisa la última línea de progreso por si hubo error.
    lines = [l for l in raw.decode('utf-8', errors='replace').splitlines() if l.strip()]
    for line in lines[-5:]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get('error'):
            return False, obj['error']
    return True, ''


def ensure_image(image):
    if image_exists(image):
        return True, ''
    return pull_image(image)


def remove_container(name, force=True):
    request('DELETE', f'/containers/{name}?force={"true" if force else "false"}')


def create_container(name, image, env=None, ports=None, binds=None, network=None, cmd=None,
                      working_dir=None, restart='unless-stopped'):
    """ports: {'80/tcp': host_port}. binds: ['/host/path:/container/path']."""
    exposed = {}
    port_bindings = {}
    for container_port, host_port in (ports or {}).items():
        exposed[container_port] = {}
        port_bindings[container_port] = [{'HostPort': str(host_port)}]

    host_config = {
        'Binds': binds or [],
        'PortBindings': port_bindings,
        'RestartPolicy': {'Name': restart},
    }
    if network:
        host_config['NetworkMode'] = network

    payload = {
        'Image': image,
        'Env': [f'{k}={v}' for k, v in (env or {}).items()],
        'ExposedPorts': exposed,
        'HostConfig': host_config,
    }
    if cmd:
        payload['Cmd'] = cmd
    if working_dir:
        payload['WorkingDir'] = working_dir
    if network:
        payload['NetworkingConfig'] = {'EndpointsConfig': {network: {}}}

    remove_container(name)
    status, raw = request('POST', f'/containers/create?name={name}', body=payload, timeout=60)
    if status not in (201,):
        return None, raw.decode('utf-8', errors='replace')
    container_id = json.loads(raw)['Id']
    status, raw = request('POST', f'/containers/{container_id}/start', timeout=30)
    if status not in (204,):
        return None, raw.decode('utf-8', errors='replace')
    return container_id, ''


def update_container_resources(container, cpus=None, mem_limit_mb=None):
    """Ajusta límites de CPU/RAM de un contenedor ya existente, sin recrearlo."""
    payload = {}
    if cpus:
        payload['NanoCpus'] = int(float(cpus) * 1e9)
    if mem_limit_mb:
        payload['Memory'] = int(mem_limit_mb) * 1024 * 1024
    if not payload:
        payload = {'NanoCpus': 0, 'Memory': 0}  # quita los límites
    status, raw = request('POST', f'/containers/{container}/update', body=payload, timeout=20)
    if status not in (200,):
        return False, raw.decode('utf-8', errors='replace')
    return True, ''


def export_volume_tar(volume_name):
    """Exporta un volumen con nombre a bytes tar, vía un contenedor descartable."""
    helper = f'backup-export-{volume_name}'
    remove_container(helper)
    status, raw = request('POST', f'/containers/create?name={helper}', body={
        'Image': 'alpine',
        'Cmd': ['true'],
        'HostConfig': {'Binds': [f'{volume_name}:/data:ro']},
    }, timeout=30)
    if status not in (201,):
        return None, raw.decode('utf-8', errors='replace')
    try:
        status, raw = request('GET', f'/containers/{helper}/archive?path=/data', timeout=120)
        if status != 200:
            return None, raw.decode('utf-8', errors='replace')
        return raw, ''
    finally:
        remove_container(helper)


def import_volume_tar(volume_name, tar_bytes):
    """Restaura bytes tar (como los de export_volume_tar) dentro de un volumen nuevo."""
    ok, err = ensure_volume(volume_name)
    if not ok:
        return False, err
    helper = f'backup-import-{volume_name}'
    remove_container(helper)
    status, raw = request('POST', f'/containers/create?name={helper}', body={
        'Image': 'alpine',
        'Cmd': ['true'],
        'HostConfig': {'Binds': [f'{volume_name}:/data']},
    }, timeout=30)
    if status not in (201,):
        return False, raw.decode('utf-8', errors='replace')
    try:
        status, raw = request(
            'PUT', f'/containers/{helper}/archive?path=/data',
            raw_body=tar_bytes, timeout=180,
        )
        if status not in (200,):
            return False, raw.decode('utf-8', errors='replace')
        return True, ''
    finally:
        remove_container(helper)
