"""Generación de sitios Nginx + recarga y emisión de certificados SSL,
todo hablando directo con el socket de Docker (sin dependencias extra)."""
import json
import os
import re
import struct

from docker_control import DOCKER_SOCK, _DockerSocketConnection

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


def nginx_test(container='proxy'):
    code, out = docker_exec(container, ['nginx', '-t'])
    return code == 0, out


def nginx_reload(container='proxy'):
    code, out = docker_exec(container, ['nginx', '-s', 'reload'])
    return code == 0, out


def _site_filename(domain):
    if not DOMAIN_FILE_RE.match(domain or ''):
        raise ValueError('Dominio inválido.')
    return f'{domain}.conf'


def render_site_conf(domain, target_host, target_port, ssl_ready):
    # Se usa "resolver" + variable en proxy_pass, en vez de un bloque
    # "upstream" con IP fija, para que nginx vuelva a resolver el nombre en
    # cada request. Si no, cuando el contenedor destino se recrea (ej. al
    # reiniciarlo a mano) le toca IP nueva y el sitio queda en 502 hasta el
    # próximo "nginx -s reload".
    upstream_var = '$upstream_' + re.sub(r'[^a-z0-9]+', '_', domain.lower()).strip('_')
    proxy_headers = (
        f'        set {upstream_var} {target_host}:{target_port};\n'
        f'        proxy_pass http://{upstream_var};\n'
        f'        proxy_http_version 1.1;\n'
        f'        proxy_set_header Host $host;\n'
        f'        proxy_set_header X-Real-IP $remote_addr;\n'
        f'        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n'
        f'        proxy_set_header X-Forwarded-Proto $scheme;\n'
    )

    if not ssl_ready:
        return (
            f'# panel:managed domain={domain} target={target_host}:{target_port} ssl=pending\n'
            'server {\n'
            f'    listen 80;\n'
            f'    server_name {domain};\n\n'
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
        f'    server_name {domain};\n\n'
        '    location /.well-known/acme-challenge/ {\n'
        '        root /var/www/certbot;\n'
        '    }\n\n'
        '    location / {\n'
        '        return 301 https://$host$request_uri;\n'
        '    }\n'
        '}\n\n'
        'server {\n'
        f'    listen 443 ssl;\n'
        f'    http2 on;\n'
        f'    server_name {domain};\n\n'
        f'    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;\n'
        f'    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;\n'
        '    ssl_protocols TLSv1.2 TLSv1.3;\n'
        '    ssl_prefer_server_ciphers off;\n\n'
        '    location / {\n'
        + proxy_headers +
        '        proxy_read_timeout 300s;\n'
        '        proxy_send_timeout 300s;\n'
        '        proxy_connect_timeout 10s;\n'
        '    }\n'
        '}\n'
    )


def apply_site(sites_dir, domain, target_host, target_port, ssl_ready, proxy_container='proxy'):
    path = os.path.join(sites_dir, _site_filename(domain))
    previous = None
    if os.path.isfile(path):
        with open(path, encoding='utf-8') as fh:
            previous = fh.read()

    content = render_site_conf(domain, target_host, target_port, ssl_ready)
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


def remove_site(sites_dir, domain, proxy_container='proxy'):
    path = os.path.join(sites_dir, _site_filename(domain))
    if os.path.isfile(path):
        os.remove(path)
    return nginx_reload(proxy_container)


def issue_certificate(domain, email, certbot_container='proxy-certbot'):
    cmd = [
        'certbot', 'certonly', '--webroot', '-w', '/var/www/certbot',
        '-d', domain, '--email', email, '--agree-tos', '--no-eff-email',
        '--non-interactive',
    ]
    code, out = docker_exec(certbot_container, cmd, timeout=120)
    return code == 0, out
