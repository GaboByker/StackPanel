"""Detecta carpetas dentro de html/ que todavía no están registradas en el
panel (por ejemplo, un proyecto creado a mano por SSH), y trata de adivinar
sus contenedores/puerto cruzando con lo que ya está corriendo en Docker."""
import os
import re

import docker_control


def _compose_project_name(dir_name):
    # Así deriva Docker Compose el nombre de proyecto a partir de una carpeta.
    return re.sub(r'[^a-z0-9_-]', '', dir_name.lower())


def scan_candidates(stack_root, registered_folders):
    html_root = os.path.join(stack_root, 'html')
    if not os.path.isdir(html_root):
        return []

    containers, _err = docker_control.list_all_containers()
    registered = set(registered_folders or [])

    candidates = []
    for dir_name in sorted(os.listdir(html_root)):
        full = os.path.join(html_root, dir_name)
        if not os.path.isdir(full):
            continue
        folder = f'html/{dir_name}'
        if folder in registered:
            continue

        compose_project = _compose_project_name(dir_name)
        matched = [
            c for c in containers
            if c['labels'].get('com.docker.compose.project') == compose_project
            or c['name'].lower().startswith(dir_name.lower())
        ]
        container_names = sorted({c['name'] for c in matched})
        ports = sorted({p for c in matched for p in c['host_ports']})
        running = any(c['state'] == 'running' for c in matched)
        # Si el contenedor publica varios puertos (p.ej. un dev server y el
        # sitio real), probamos cuál responde HTTP en vez de asumir el más
        # bajo; si ninguno responde (o no está corriendo) usamos el primero.
        port_guess = None
        if ports:
            port_guess = docker_control.pick_http_port(ports) if running else None
            if port_guess is None:
                port_guess = ports[0]

        candidates.append({
            'folder': folder,
            'dir_name': dir_name,
            'name_guess': dir_name.replace('-', ' ').replace('_', ' ').title(),
            'containers': container_names,
            'port_guess': port_guess,
            'port_options': ports,
            'running': running,
        })
    return candidates
