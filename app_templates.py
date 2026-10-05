"""Catálogo de apps de 1 clic. Cada plantilla crea su propio contenedor
(o par app+BD) con datos en una carpeta bajo html/<slug>/, para que quede
editable desde el explorador y respaldable como cualquier otro proyecto."""
import os
import secrets
import time

import docker_control
import docker_ops

TEMPLATES = {
    'wordpress': {
        'label': 'WordPress',
        'description': 'Sitio WordPress con su propia base de datos MariaDB.',
        'default_container_port': 80,
    },
    'static': {
        'label': 'Sitio estático',
        'description': 'Página HTML/CSS/JS estática servida con nginx.',
        'default_container_port': 80,
    },
    'flask': {
        'label': 'App Flask vacía',
        'description': 'Esqueleto Python/Flask listo para editar desde el explorador.',
        'default_container_port': 5000,
    },
    'node': {
        'label': 'App Node vacía',
        'description': 'Esqueleto Node.js listo para editar desde el explorador.',
        'default_container_port': 3000,
    },
}


PHP_INI_RELATIVE = os.path.join('php-config', 'zz-panel.ini')
PHP_INI_CONTAINER_PATH = '/usr/local/etc/php/conf.d/zz-panel.ini'
DEFAULT_PHP_CONFIG = {
    'upload_max_filesize': '64M',
    'post_max_size': '64M',
    'memory_limit': '256M',
    'max_execution_time': '300',
    'max_input_vars': '3000',
}


def _php_ini_local_path(local_folder):
    return os.path.join(local_folder, PHP_INI_RELATIVE)


def _php_ini_host_path(host_folder):
    return f"{host_folder}/{PHP_INI_RELATIVE.replace(os.sep, '/')}"


def read_php_config(local_folder):
    values = dict(DEFAULT_PHP_CONFIG)
    path = _php_ini_local_path(local_folder)
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith(';') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                key = key.strip()
                if key in values:
                    values[key] = val.strip()
    return values


def write_php_config(local_folder, values):
    path = _php_ini_local_path(local_folder)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [f'{key} = {(values.get(key) or "").strip() or default}' for key, default in DEFAULT_PHP_CONFIG.items()]
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')


def ensure_php_override_mount(app_container, local_folder, host_folder):
    """Se asegura de que el contenedor tenga montado el .ini de overrides.
    Los sitios instalados antes de que existiera esta función no lo tienen,
    así que hay que recrear el contenedor agregándolo (sin tocar wp-content
    ni la base, que viven en sus propios binds). Devuelve (ok, err, recreado)."""
    if not os.path.isfile(_php_ini_local_path(local_folder)):
        write_php_config(local_folder, DEFAULT_PHP_CONFIG)

    info = docker_ops.inspect_container(app_container)
    if not info:
        return False, 'No se encontró el contenedor de la aplicación.', False

    bind_entry = f'{_php_ini_host_path(host_folder)}:{PHP_INI_CONTAINER_PATH}'
    if any(b.split(':', 1)[-1] == PHP_INI_CONTAINER_PATH for b in info['binds']):
        return True, '', False

    binds = info['binds'] + [bind_entry]
    _, err = docker_ops.create_container(
        app_container, info['image'], env=info['env'], ports=info['ports'],
        binds=binds, network=info['network'],
    )
    if err:
        return False, err, False
    return True, '', True


def save_php_config(app_container, local_folder, host_folder, values):
    write_php_config(local_folder, values)
    ok, err, recreated = ensure_php_override_mount(app_container, local_folder, host_folder)
    if not ok:
        return False, err
    if not recreated:
        # El bind ya estaba montado: PHP solo relee el .ini al arrancar,
        # así que hace falta un restart para que tome los valores nuevos.
        ok, msg = docker_control.stop_containers([app_container])
        if not ok:
            return False, msg
        ok, msg = docker_control.start_containers([app_container])
        if not ok:
            return False, msg
    return True, ''


def _wait_mysql_ready(container, attempts=30, delay=1):
    """MariaDB hace un primer arranque interno para crear la base/usuario
    antes de quedar lista; si WordPress arranca y alguien entra al sitio en
    esa ventana, ve 'Error establishing a database connection'. Se espera
    a que el propio healthcheck de la imagen confirme que ya puede
    atender conexiones reales."""
    for _ in range(attempts):
        if docker_ops.exec_run(container, ['healthcheck.sh', '--connect', '--innodb_initialized']) == 0:
            return True
        time.sleep(delay)
    return False


def pick_free_port(used_ports, start=20000, end=20999):
    used = set(p for p in (used_ports or []) if p)
    for port in range(start, end + 1):
        if port not in used:
            return port
    return None


def install(template, slug, local_folder, host_folder, port, saved_secrets=None):
    """local_folder: ruta absoluta donde el propio panel escribe archivos
    (montaje de escritura del panel). host_folder: la misma carpeta pero
    vista como ruta del host real, la que necesita Docker para los binds,
    porque el daemon de Docker monta rutas del host, no del contenedor del
    panel. Devuelve (containers, volumes, secrets, error); secrets se debe
    guardar en el proyecto y reenviarse aquí mismo si algún día se
    reinstala/restaura, para que la app recién creada siga usando las
    mismas credenciales que los datos restaurados (ej. la contraseña que
    WordPress espera de MariaDB)."""
    fn = {
        'wordpress': _install_wordpress,
        'static': _install_static,
        'flask': _install_flask,
        'node': _install_node,
    }.get(template)
    if not fn:
        return None, None, None, 'Plantilla desconocida.'
    return fn(slug, local_folder, host_folder, port, saved_secrets or {})


def _install_wordpress(slug, local_folder, host_folder, port, saved_secrets):
    network = f'{slug}-net'
    db_container = f'{slug}-db'
    app_container = f'{slug}-app'
    db_password = saved_secrets.get('db_password') or secrets.token_hex(12)
    root_password = saved_secrets.get('root_password') or secrets.token_hex(12)
    # Tag sin versión fija: Docker Hub lo actualiza a la última WordPress
    # estable para PHP 8.2, así los sitios nuevos no nacen desactualizados.
    wp_image = 'wordpress:php8.2-apache'

    os.makedirs(os.path.join(local_folder, 'db-data'), exist_ok=True)
    os.makedirs(os.path.join(local_folder, 'wp-content'), exist_ok=True)

    ok, err = docker_ops.ensure_network(network)
    if not ok:
        return None, None, None, err
    ok, err = docker_ops.ensure_image('mariadb:11')
    if not ok:
        return None, None, None, err
    # A diferencia de ensure_image (que reusa la imagen si ya existe en el
    # host), acá forzamos el pull para traer la versión vigente aunque haya
    # quedado una imagen vieja cacheada de una instalación anterior. Si no
    # hay red pero ya hay una imagen local, seguimos con esa.
    ok, err = docker_ops.pull_image(wp_image)
    if not ok and not docker_ops.image_exists(wp_image):
        return None, None, None, err

    secrets_out = {'db_password': db_password, 'root_password': root_password}

    _, err = docker_ops.create_container(
        db_container, 'mariadb:11',
        env={
            'MYSQL_DATABASE': 'wordpress',
            'MYSQL_USER': 'wordpress',
            'MYSQL_PASSWORD': db_password,
            'MYSQL_ROOT_PASSWORD': root_password,
        },
        binds=[f'{host_folder}/db-data:/var/lib/mysql'],
        network=network,
    )
    if err:
        return None, None, None, err

    if not _wait_mysql_ready(db_container):
        return None, None, None, 'MariaDB no respondió a tiempo al iniciar. Intenta instalar de nuevo.'

    write_php_config(local_folder, DEFAULT_PHP_CONFIG)

    _, err = docker_ops.create_container(
        app_container, wp_image,
        env={
            'WORDPRESS_DB_HOST': db_container,
            'WORDPRESS_DB_USER': 'wordpress',
            'WORDPRESS_DB_PASSWORD': db_password,
            'WORDPRESS_DB_NAME': 'wordpress',
        },
        binds=[
            f'{host_folder}/wp-content:/var/www/html/wp-content',
            f'{_php_ini_host_path(host_folder)}:{PHP_INI_CONTAINER_PATH}',
        ],
        ports={'80/tcp': port},
        network=network,
    )
    if err:
        return None, None, None, err

    # El panel necesita poder alcanzar la base de este sitio para poder
    # detectarla/explorarla (cada sitio vive en su propia red aislada para
    # que no se vean entre sí). Best-effort: si falla, el sitio funciona
    # igual, solo no se podrá auto-detectar la conexión desde el panel.
    docker_ops.connect_network(network, os.environ.get('HOSTNAME'))

    return [db_container, app_container], [], secrets_out, None


def _install_static(slug, local_folder, host_folder, port, saved_secrets):
    public_dir = os.path.join(local_folder, 'public')
    host_public_dir = f'{host_folder}/public'
    os.makedirs(public_dir, exist_ok=True)
    index_path = os.path.join(public_dir, 'index.html')
    if not os.path.exists(index_path):
        with open(index_path, 'w', encoding='utf-8') as fh:
            fh.write(
                '<!doctype html><html lang="es"><head><meta charset="utf-8">'
                f'<title>{slug}</title></head><body style="font-family:sans-serif;padding:40px;">'
                f'<h1>{slug}</h1><p>Sitio estático nuevo. Edita los archivos de <code>public/</code> '
                'desde el explorador del panel.</p></body></html>'
            )

    ok, err = docker_ops.ensure_image('nginx:alpine')
    if not ok:
        return None, None, None, err

    container = f'{slug}-web'
    _, err = docker_ops.create_container(
        container, 'nginx:alpine',
        binds=[f'{host_public_dir}:/usr/share/nginx/html:ro'],
        ports={'80/tcp': port},
    )
    if err:
        return None, None, None, err
    return [container], [], {}, None


def _install_flask(slug, local_folder, host_folder, port, saved_secrets):
    os.makedirs(local_folder, exist_ok=True)
    app_py = os.path.join(local_folder, 'app.py')
    if not os.path.exists(app_py):
        with open(app_py, 'w', encoding='utf-8') as fh:
            fh.write(
                "from flask import Flask\n\napp = Flask(__name__)\n\n"
                "@app.route('/')\ndef home():\n"
                f"    return 'Hola desde {slug} (Flask)'\n\n"
                "if __name__ == '__main__':\n    app.run(host='0.0.0.0', port=5000)\n"
            )
    req = os.path.join(local_folder, 'requirements.txt')
    if not os.path.exists(req):
        with open(req, 'w', encoding='utf-8') as fh:
            fh.write('flask>=3.0\n')

    ok, err = docker_ops.ensure_image('python:3.12-slim')
    if not ok:
        return None, None, None, err

    container = f'{slug}-app'
    _, err = docker_ops.create_container(
        container, 'python:3.12-slim',
        binds=[f'{host_folder}:/app'],
        working_dir='/app',
        cmd=['sh', '-c', 'pip install --no-cache-dir -r requirements.txt && python app.py'],
        ports={'5000/tcp': port},
    )
    if err:
        return None, None, None, err
    return [container], [], {}, None


def _install_node(slug, local_folder, host_folder, port, saved_secrets):
    os.makedirs(local_folder, exist_ok=True)
    index_js = os.path.join(local_folder, 'index.js')
    if not os.path.exists(index_js):
        with open(index_js, 'w', encoding='utf-8') as fh:
            fh.write(
                "const http = require('http');\n"
                "const port = process.env.PORT || 3000;\n"
                "http.createServer((req, res) => {\n"
                f"  res.end('Hola desde {slug} (Node)');\n"
                "}).listen(port, '0.0.0.0', () => console.log('listening on ' + port));\n"
            )
    pkg = os.path.join(local_folder, 'package.json')
    if not os.path.exists(pkg):
        with open(pkg, 'w', encoding='utf-8') as fh:
            fh.write(
                '{\n  "name": "%s",\n  "version": "1.0.0",\n'
                '  "scripts": { "start": "node index.js" }\n}\n' % slug
            )

    ok, err = docker_ops.ensure_image('node:20-alpine')
    if not ok:
        return None, None, None, err

    container = f'{slug}-app'
    _, err = docker_ops.create_container(
        container, 'node:20-alpine',
        binds=[f'{host_folder}:/app'],
        working_dir='/app',
        cmd=['sh', '-c', 'npm install --omit=dev --no-audit --no-fund || true; npm start'],
        ports={'3000/tcp': port},
    )
    if err:
        return None, None, None, err
    return [container], [], {}, None
