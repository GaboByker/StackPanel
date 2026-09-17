"""Crea un proyecto nuevo a partir de uno o más repositorios Git. Cada
repositorio se clona a su propia subcarpeta (útil cuando un proyecto es
backend + frontend en repos separados) y se levanta según lo que traiga:

- Si tiene su propio Dockerfile: se construye una imagen a partir de él.
- Si no, se detecta Python (requirements.txt/pyproject.toml) o Node
  (package.json) y se corre con una imagen base genérica, montando el
  código tal como hace "Instalar app" con sus plantillas.
- Si sólo trae HTML/CSS/JS (index.html, o en public/dist/build), se sirve
  con nginx.

Todos los contenedores del proyecto quedan en una red privada propia con
alias = su "rol" (ej. "backend", "frontend"), así uno puede llamar al otro
por ese nombre sin que la URL pública tenga nada que ver."""
import io
import json
import os
import shutil
import subprocess
import tarfile

import docker_ops

_ENTRY_CANDIDATES_PY = ['app.py', 'main.py', 'wsgi.py', 'server.py']
_STATIC_SUBDIRS = ('', 'public', 'dist', 'build')


def clone_repo(url, branch, dest):
    if os.path.exists(dest):
        return False, f'La carpeta {dest} ya existe.'
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
    cmd = ['git', 'clone', '--depth', '1']
    if branch:
        cmd += ['--branch', branch]
    cmd += [url, dest]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return False, 'Se agotó el tiempo clonando el repositorio (más de 5 minutos).'
    except OSError as exc:
        return False, str(exc)
    if result.returncode != 0:
        msg = (result.stderr or result.stdout or 'git clone falló').strip()
        return False, msg[-800:]
    return True, ''


def pull_repo(local_dir):
    try:
        result = subprocess.run(
            ['git', '-C', local_dir, 'pull', '--ff-only'],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, 'Se agotó el tiempo haciendo git pull.'
    except OSError as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or 'git pull falló').strip()[-800:]
    return True, (result.stdout or '').strip()


def detect_kind(local_dir, dockerfile_hint=None):
    dockerfile = dockerfile_hint or 'Dockerfile'
    if os.path.isfile(os.path.join(local_dir, dockerfile)):
        return 'dockerfile'
    if os.path.isfile(os.path.join(local_dir, 'package.json')):
        return 'node'
    if os.path.isfile(os.path.join(local_dir, 'requirements.txt')) or os.path.isfile(os.path.join(local_dir, 'pyproject.toml')):
        return 'python'
    if _static_subdir(local_dir) is not None:
        return 'static'
    return None


def _static_subdir(local_dir):
    for sub in _STATIC_SUBDIRS:
        if os.path.isfile(os.path.join(local_dir, sub, 'index.html')):
            return sub
    return None


def _guess_python_command(local_dir):
    procfile = os.path.join(local_dir, 'Procfile')
    if os.path.isfile(procfile):
        with open(procfile, encoding='utf-8', errors='ignore') as fh:
            for line in fh:
                if line.strip().startswith('web:'):
                    return line.split(':', 1)[1].strip()
    for name in _ENTRY_CANDIDATES_PY:
        if os.path.isfile(os.path.join(local_dir, name)):
            return f'python {name}'
    return None


def _guess_node_command(local_dir):
    try:
        with open(os.path.join(local_dir, 'package.json'), encoding='utf-8') as fh:
            pkg = json.load(fh)
    except (OSError, ValueError):
        pkg = {}
    scripts = pkg.get('scripts') or {}
    if 'start' in scripts:
        return 'npm start'
    if 'dev' in scripts:
        return 'npm run dev'
    main = pkg.get('main')
    return f'node {main}' if main else None


def build_image_from_dockerfile(local_dir, tag, dockerfile='Dockerfile'):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        tar.add(local_dir, arcname='.')
    status, raw = docker_ops.request(
        'POST', f'/build?t={tag}&dockerfile={dockerfile}&rm=1',
        raw_body=buf.getvalue(), timeout=900,
    )
    if status >= 400:
        return False, raw.decode('utf-8', errors='replace')[-1500:]
    lines = [l for l in raw.decode('utf-8', errors='replace').splitlines() if l.strip()]
    for line in lines[-20:]:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get('error'):
            return False, obj['error']
    return True, ''


def _cleanup(containers, network, local_folder):
    for name in containers:
        docker_ops.remove_container(name, force=True)
    if network:
        docker_ops.request('DELETE', f'/networks/{network}')
    if local_folder and os.path.isdir(local_folder):
        shutil.rmtree(local_folder, ignore_errors=True)


def create_from_repos(local_folder, host_folder, key, repos, public_index, public_port):
    """repos: lista de dicts {url, branch, role, container_port, command, dockerfile}.
    Devuelve (repos_result, containers, error, warnings)."""
    warnings = []
    containers = []
    repos_result = []
    network = f'{key}-net'

    ok, err = docker_ops.ensure_network(network)
    if not ok:
        return None, None, f'No se pudo crear la red del proyecto: {err}', warnings

    for i, repo in enumerate(repos):
        role = repo['role']
        repo_local = os.path.join(local_folder, role)
        repo_host = f'{host_folder}/{role}'

        ok, err = clone_repo(repo['url'], repo.get('branch'), repo_local)
        if not ok:
            _cleanup(containers, network, local_folder)
            return None, None, f'No se pudo clonar "{repo["url"]}" ({role}): {err}', warnings

        kind = detect_kind(repo_local, repo.get('dockerfile'))
        if not kind:
            _cleanup(containers, network, local_folder)
            return None, None, (
                f'No pude detectar cómo correr el repositorio "{role}" '
                '(no encontré Dockerfile, package.json, requirements.txt/pyproject.toml ni index.html).'
            ), warnings

        container_name = f'{key}-{role}'
        container_port = repo.get('container_port')
        is_public = (i == public_index)
        host_port = public_port if is_public else None
        ports = {f'{container_port}/tcp': host_port} if (container_port and host_port) else {}

        if kind == 'dockerfile':
            tag = f'panel-git/{key}-{role}:latest'
            ok, err = build_image_from_dockerfile(repo_local, tag, repo.get('dockerfile') or 'Dockerfile')
            if not ok:
                _cleanup(containers, network, local_folder)
                return None, None, f'Falló el build de "{role}": {err}', warnings
            cid, err = docker_ops.create_container(
                container_name, tag, ports=ports, network=network, network_aliases=[role],
            )
        elif kind == 'static':
            ok, err = docker_ops.ensure_image('nginx:alpine')
            if not ok:
                _cleanup(containers, network, local_folder)
                return None, None, f'No se pudo preparar nginx para "{role}": {err}', warnings
            subdir = _static_subdir(repo_local) or ''
            binds = [f'{os.path.join(repo_host, subdir)}:/usr/share/nginx/html:ro']
            ports = {'80/tcp': host_port} if host_port else {}
            cid, err = docker_ops.create_container(
                container_name, 'nginx:alpine', ports=ports, binds=binds,
                network=network, network_aliases=[role],
            )
        else:  # python | node
            command = (repo.get('command') or '').strip() or None
            if kind == 'python':
                command = command or _guess_python_command(repo_local)
                image, setup = 'python:3.12-slim', 'pip install --no-cache-dir -r requirements.txt 2>/dev/null'
            else:
                command = command or _guess_node_command(repo_local)
                image, setup = 'node:20-alpine', 'npm install --omit=dev --no-audit --no-fund 2>/dev/null || true'
            if not command:
                _cleanup(containers, network, local_folder)
                return None, None, (
                    f'No pude adivinar cómo arrancar "{role}" ({kind}). '
                    'Indicá un comando de inicio manualmente.'
                ), warnings
            ok, err = docker_ops.ensure_image(image)
            if not ok:
                _cleanup(containers, network, local_folder)
                return None, None, f'No se pudo preparar la imagen para "{role}": {err}', warnings
            cid, err = docker_ops.create_container(
                container_name, image, ports=ports, binds=[f'{repo_host}:/app'],
                working_dir='/app', cmd=['sh', '-c', f'{setup}; {command}'],
                network=network, network_aliases=[role],
            )

        if err:
            _cleanup(containers, network, local_folder)
            return None, None, f'No se pudo levantar "{role}": {err}', warnings

        containers.append(container_name)
        repos_result.append({
            'url': repo['url'], 'branch': repo.get('branch') or '', 'role': role, 'kind': kind,
            'container': container_name, 'container_port': container_port,
            'host_port': host_port, 'public': is_public,
        })
        if not host_port:
            warnings.append(f'"{role}" quedó sólo interno; los demás lo alcanzan como "{role}"{f":{container_port}" if container_port else ""}.')

    return repos_result, containers, None, warnings
