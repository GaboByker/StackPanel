"""Sitios de Nginx, recarga y certificados SSL por el socket de Docker."""
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import struct

from docker_control import CERTBOT_CONTAINER, DOCKER_SOCK, PROXY_CONTAINER, _DockerSocketConnection

DOMAIN_FILE_RE = re.compile(r'^[a-zA-Z0-9.-]+$')


def _request(method, path, body=None, timeout=30):
    conn = _DockerSocketConnection(DOCKER_SOCK)
    conn.timeout = timeout
    try:
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        return response.status, raw
    finally:
        conn.close()


def _demux(raw):
    """Decodifica el stream stdout/stderr multiplexado de la Docker Exec API."""
    chunks = []
    i = 0
    while i + 8 <= len(raw):
        length = struct.unpack('>I', raw[i + 4:i + 8])[0]
        start = i + 8
        end = start + length
        chunks.append(raw[start:end])
        i = end
    return b''.join(chunks).decode('utf-8', errors='replace')


def docker_exec(container, cmd, timeout=90):
    """Ejecuta un comando dentro de un contenedor. Devuelve (exit_code, output)."""
    if not os.path.exists(DOCKER_SOCK):
        return None, f'No se encuentra el socket de Docker ({DOCKER_SOCK}).'
    status, raw = _request(
        'POST', f'/containers/{container}/exec',
        body={'Cmd': cmd, 'AttachStdout': True, 'AttachStderr': True},
        timeout=timeout,
    )
    if status >= 400:
        return None, raw.decode('utf-8', errors='replace')
    exec_id = json.loads(raw)['Id']

    status, raw = _request(
        'POST', f'/exec/{exec_id}/start',
        body={'Detach': False, 'Tty': False},
        timeout=timeout,
    )
    if status >= 400:
        return None, raw.decode('utf-8', errors='replace')
    output = _demux(raw)

    status, raw = _request('GET', f'/exec/{exec_id}/json', timeout=timeout)
    if status >= 400:
        return None, output
    exit_code = json.loads(raw).get('ExitCode')
    return exit_code, output


def nginx_test(container=PROXY_CONTAINER):
    code, out = docker_exec(container, ['nginx', '-t'])
    return code == 0, out


def nginx_reload(container=PROXY_CONTAINER):
    code, out = docker_exec(container, ['nginx', '-s', 'reload'])
    return code == 0, out


def _site_filename(domain):
    if not DOMAIN_FILE_RE.match(domain or ''):
        raise ValueError('Dominio inválido.')
    return f'{domain}.conf'


def companion_domain(domain):
    """La otra forma del dominio: www.x.com <-> x.com."""
    domain = domain.lower()
    return domain[4:] if domain.startswith('www.') else f'www.{domain}'


def _resolve(name):
    try:
        return {info[4][0] for info in socket.getaddrinfo(name, None)}
    except OSError:
        return set()


def site_aliases(domain, taken=(), extras=()):
    """Nombres que redirigen al dominio principal: los adicionales que agregó el admin, más el
    www/sin www automático si su DNS apunta al mismo servidor y no está enrutado por otro sitio."""
    aliases = [a for a in extras if a != domain and a not in taken]
    alias = companion_domain(domain)
    if alias not in taken and alias not in aliases:
        ips = _resolve(domain)
        if ips and _resolve(alias) & ips:
            aliases.append(alias)
    return aliases


def reachable_aliases(domain, aliases):
    """Los alias cuyo DNS ya apunta al mismo servidor que el dominio (los únicos certificables)."""
    ips = _resolve(domain)
    return [a for a in aliases if ips and _resolve(a) & ips]


SITE_KEY_FILE = os.environ.get('STACKPANEL_SITE_KEY_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'proxy-site.key'))


def site_key(target_port):
    """Clave que el proxy envía a la app de un puerto (X-StackPanel-Key): HMAC del secreto del panel y el puerto.
    Cada app solo conoce la suya: nadie puede anunciarle otro dominio entrando directo por el puerto."""
    if not os.path.isfile(SITE_KEY_FILE):
        fd = os.open(SITE_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as fh:
            fh.write(secrets.token_hex(32))
    with open(SITE_KEY_FILE, encoding='utf-8') as fh:
        secret = fh.read().strip()
    return hmac.new(secret.encode(), str(int(target_port)).encode(), hashlib.sha256).hexdigest()


def render_site_conf(domain, target_host, target_port, ssl_ready, aliases=()):
    # resolver + variable hace que nginx resuelva el nombre en cada petición (evita 502 si el
    # contenedor cambia de IP). host.docker.internal solo está en /etc/hosts y va directo.
    if target_host == 'host.docker.internal' or re.fullmatch(r'[0-9.]+', target_host):
        upstream_lines = f'        proxy_pass http://{target_host}:{target_port};\n'
    else:
        upstream_var = '$upstream_' + re.sub(r'[^a-z0-9]+', '_', domain.lower()).strip('_')
        upstream_lines = (
            f'        set {upstream_var} {target_host}:{target_port};\n'
            f'        proxy_pass http://{upstream_var};\n'
        )
    proxy_headers = (
        upstream_lines +
        f'        proxy_http_version 1.1;\n'
        f'        proxy_set_header Host $host;\n'
        f'        proxy_set_header X-Real-IP $remote_addr;\n'
        f'        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n'
        f'        proxy_set_header X-Forwarded-Proto $scheme;\n'
        # URL fija de la config (no el Host del visitante) firmada para la app: WordPress la usa para seguir el dominio
        f'        proxy_set_header X-StackPanel-Url {"https" if ssl_ready else "http"}://{domain};\n'
        f'        proxy_set_header X-StackPanel-Key {site_key(target_port)};\n'
    )

    alias_names = ' '.join(aliases)
    names = f'{domain} {alias_names}'.strip()
    ssl_lines = (
        f'    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;\n'
        f'    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;\n'
        '    ssl_protocols TLSv1.2 TLSv1.3;\n'
        '    ssl_prefer_server_ciphers off;\n\n'
    )
    # Los alias comparten el certificado del dominio principal y redirigen a él.
    alias_block = (
        'server {\n'
        '    listen 443 ssl;\n'
        '    http2 on;\n'
        f'    server_name {alias_names};\n\n'
        + ssl_lines +
        f'    return 301 https://{domain}$request_uri;\n'
        '}\n\n'
    ) if aliases else ''
    if not ssl_ready:
        return (
            f'# panel:managed domain={domain} target={target_host}:{target_port} ssl=pending\n'
            'server {\n'
            f'    listen 80;\n'
            f'    server_name {names};\n\n'
            '    location /.well-known/acme-challenge/ {\n'
            '        root /var/www/certbot;\n'
            '    }\n\n'
            '    location / {\n'
            + proxy_headers +
            '    }\n'
            '}\n'
        )

    return (
        f'# panel:managed domain={domain} target={target_host}:{target_port} ssl=on\n'
        'server {\n'
        f'    listen 80;\n'
        f'    server_name {names};\n\n'
        '    location /.well-known/acme-challenge/ {\n'
        '        root /var/www/certbot;\n'
        '    }\n\n'
        '    location / {\n'
        f'        return 301 https://{domain}$request_uri;\n'
        '    }\n'
        '}\n\n'
        + alias_block +
        'server {\n'
        f'    listen 443 ssl;\n'
        f'    http2 on;\n'
        f'    server_name {domain};\n\n'
        + ssl_lines +
        '    location / {\n'
        + proxy_headers +
        '        proxy_read_timeout 300s;\n'
        '        proxy_send_timeout 300s;\n'
        '        proxy_connect_timeout 10s;\n'
        '    }\n'
        '}\n'
    )


def apply_site(sites_dir, domain, target_host, target_port, ssl_ready, proxy_container=PROXY_CONTAINER, aliases=()):
    path = os.path.join(sites_dir, _site_filename(domain))
    previous = None
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as fh:
            previous = fh.read()

    content = render_site_conf(domain, target_host, target_port, ssl_ready, aliases)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(content)

    ok, out = nginx_test(proxy_container)
    if not ok:
        if previous is not None:
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(previous)
        else:
            os.remove(path)
        return False, f'Config inválida, se revirtió el cambio: {out.strip()}'

    ok, out = nginx_reload(proxy_container)
    if not ok:
        return False, f'nginx -t pasó pero no se pudo recargar: {out.strip()}'
    return True, ''


def remove_site(sites_dir, domain, proxy_container=PROXY_CONTAINER):
    path = os.path.join(sites_dir, _site_filename(domain))
    if os.path.isfile(path):
        os.remove(path)
    return nginx_reload(proxy_container)


def issue_certificate(domain, email, certbot_container=CERTBOT_CONTAINER, aliases=()):
    # --cert-name fija la ruta live/<dominio>/ aunque cambien los alias; --expand los agrega.
    cmd = [
        'certbot', 'certonly', '--webroot', '-w', '/var/www/certbot',
        '--cert-name', domain, '--expand',
        '-d', domain, *[a for alias in aliases for a in ('-d', alias)],
        '--agree-tos', '--no-eff-email', '--non-interactive',
    ]
    # Sin correo Let's Encrypt emite igual, pero no avisa del vencimiento.
    cmd += ['--email', email] if email else ['--register-unsafely-without-email']
    code, out = docker_exec(certbot_container, cmd, timeout=120)
    return code == 0, out
