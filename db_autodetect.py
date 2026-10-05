"""Detecta credenciales de base de datos en el .env de un proyecto y prueba
varias formas de conectar (host.docker.internal con el puerto publicado, o
el nombre del servicio/contenedor de su docker-compose.yml) hasta encontrar
una que funcione de verdad. Así, agregar la conexión en "Bases de datos" es
un solo clic, sin tener que ir a buscar las credenciales a mano."""
import json
import os
import re

import db_viewer
import docker_ops

# (engine, usuario, password, nombre_bd, puerto, puerto_por_defecto)
_ENV_PATTERNS = [
    ('postgres', 'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB', 'POSTGRES_PORT', 5432),
    ('mysql', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DATABASE', 'MYSQL_PORT', 3306),
    ('mysql', 'MARIADB_USER', 'MARIADB_PASSWORD', 'MARIADB_DATABASE', 'MARIADB_PORT', 3306),
]

# Apps instaladas con el instalador de 1 clic del panel: no tienen .env (las
# credenciales se pasan directo como variables del contenedor), pero como el
# panel las generó, ya sabemos exactamente cómo conectarnos.
_TEMPLATE_CONVENTIONS = {
    'wordpress': lambda slug, secrets: {
        'engine': 'mysql',
        'host': f'{slug}-db',
        'port': 3306,
        'username': 'wordpress',
        'password': secrets.get('db_password', ''),
        'dbname': 'wordpress',
    },
}


def detect_from_template(project):
    template = (project or {}).get('template')
    builder = _TEMPLATE_CONVENTIONS.get(template)
    slug = (project or {}).get('project_key')
    if not builder or not slug:
        return None
    try:
        project_secrets = json.loads(project.get('secrets') or '{}')
    except (TypeError, ValueError):
        project_secrets = {}
    candidate = builder(slug, project_secrets)
    # Cada sitio vive en su propia red de Docker aislada de los demás; el
    # panel necesita unirse a esa red para poder alcanzar la base. Si ya
    # está conectado (instalaciones nuevas) esto no hace nada.
    docker_ops.connect_network(f'{slug}-net', os.environ.get('HOSTNAME'))
    return candidate


def _read_env(folder):
    env = {}
    path = os.path.join(folder, '.env')
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
    return env


def _compose_service_names(folder):
    """Nombres de contenedor que suenen a base de datos, leídos del
    docker-compose.yml del proyecto (si existe), para probarlos como host."""
    names = []
    for fname in ('docker-compose.yml', 'docker-compose.yaml'):
        path = os.path.join(folder, fname)
        if not os.path.isfile(path):
            continue
        with open(path, encoding='utf-8') as fh:
            text = fh.read()
        for m in re.finditer(r'container_name:\s*([a-zA-Z0-9_.-]+)', text):
            name = m.group(1)
            if re.search(r'(db|postgres|mysql|mariadb|sql)', name, re.IGNORECASE):
                names.append(name)
    return names


def detect_candidates(folder):
    env = _read_env(folder)
    candidates = []
    seen = set()
    for engine, user_key, pass_key, db_key, port_key, default_port in _ENV_PATTERNS:
        if user_key not in env or db_key not in env:
            continue
        username = env[user_key]
        password = env.get(pass_key, '')
        dbname = env[db_key]
        ports = {default_port}
        if env.get(port_key):
            try:
                ports.add(int(env[port_key]))
            except ValueError:
                pass
        hosts = ['host.docker.internal'] + _compose_service_names(folder)
        for host in hosts:
            for port in ports:
                key = (engine, host, port, username, dbname)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    'engine': engine, 'host': host, 'port': port,
                    'username': username, 'password': password, 'dbname': dbname,
                })
    return candidates


def autodetect(folder, project=None):
    candidates = []
    template_candidate = detect_from_template(project)
    if template_candidate:
        candidates.append(template_candidate)
    candidates += detect_candidates(folder)
    if not candidates:
        return None, 'No se encontraron credenciales de base de datos en el .env de este proyecto.'
    for candidate in candidates:
        ok, _err = db_viewer.test_connection(candidate)
        if ok:
            return candidate, None
    return None, (
        f'Se encontraron credenciales pero ninguna de las {len(candidates)} formas de conectar '
        'funcionó (probé host.docker.internal y los nombres de contenedor del docker-compose.yml). '
        'Puede que la base de datos esté en una red de Docker aislada; agrégala manualmente.'
    )
