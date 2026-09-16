"""Catálogo de apps de 1 clic. Cada plantilla crea su propio contenedor
(o par app+BD) con datos en una carpeta bajo html/<slug>/, para que quede
editable desde el explorador y respaldable como cualquier otro proyecto."""
import os
import secrets

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

    os.makedirs(os.path.join(local_folder, 'db-data'), exist_ok=True)
    os.makedirs(os.path.join(local_folder, 'wp-content'), exist_ok=True)

    for step in (
        lambda: docker_ops.ensure_network(network),
        lambda: docker_ops.ensure_image('mariadb:11'),
        lambda: docker_ops.ensure_image('wordpress:6.7-php8.2-apache'),
    ):
        ok, err = step()
        if not ok:
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

    _, err = docker_ops.create_container(
        app_container, 'wordpress:6.7-php8.2-apache',
        env={
            'WORDPRESS_DB_HOST': db_container,
            'WORDPRESS_DB_USER': 'wordpress',
            'WORDPRESS_DB_PASSWORD': db_password,
            'WORDPRESS_DB_NAME': 'wordpress',
        },
        binds=[f'{host_folder}/wp-content:/var/www/html/wp-content'],
        ports={'80/tcp': port},
        network=network,
    )
    if err:
        return None, None, None, err

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
