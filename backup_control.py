"""Backups de proyecto: comprime la carpeta (con exclusiones razonables) y
cualquier volumen Docker asociado en un solo .tar.gz, y permite restaurarlo."""
import io
import json
import os
import tarfile

import docker_ops

EXCLUDE_DIRS = {'.git', 'node_modules', '.venv', '__pycache__', 'graphify-out'}


def build_backup(folder_abs, volumes, manifest=None):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        if manifest:
            payload = json.dumps(manifest).encode('utf-8')
            info = tarfile.TarInfo(name='panel-backup.json')
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))

        if folder_abs and os.path.isdir(folder_abs):
            for root, dirs, files in os.walk(folder_abs):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for name in files:
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, folder_abs)
                    try:
                        tar.add(full, arcname=os.path.join('project', rel), recursive=False)
                    except OSError:
                        continue

        for vol in (volumes or []):
            vol_bytes, _err = docker_ops.export_volume_tar(vol)
            if not vol_bytes:
                continue
            with tarfile.open(fileobj=io.BytesIO(vol_bytes)) as inner:
                for member in inner.getmembers():
                    fobj = inner.extractfile(member) if member.isfile() else None
                    member.name = os.path.join('volumes', vol, member.name.lstrip('./'))
                    tar.addfile(member, fobj)
    return buf.getvalue()


def read_backup_manifest(tar_bytes):
    """Lee panel-backup.json de la raíz del tar si existe (metadatos de plantilla)."""
    import json
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode='r:gz') as tar:
            member = next((m for m in tar.getmembers() if m.name == 'panel-backup.json'), None)
            if not member:
                return None
            return json.loads(tar.extractfile(member).read().decode('utf-8'))
    except (tarfile.TarError, OSError, ValueError):
        return None


def restore_backup(tar_bytes, dest_folder_abs, volume_name_map=None):
    os.makedirs(dest_folder_abs, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode='r:gz') as tar:
        project_members = []
        for member in tar.getmembers():
            if member.name == 'project' or member.name.startswith('project/'):
                member.name = os.path.relpath(member.name, 'project')
                if member.name != '.':
                    project_members.append(member)
        if project_members:
            tar.extractall(path=dest_folder_abs, members=project_members, filter='data')

        volumes_found = {}
        for member in tar.getmembers():
            if member.name.startswith('volumes/'):
                parts = member.name.split('/', 2)
                if len(parts) >= 3:
                    volumes_found.setdefault(parts[1], []).append(member)

        for old_name, members in volumes_found.items():
            new_name = (volume_name_map or {}).get(old_name, old_name)
            sub_buf = io.BytesIO()
            with tarfile.open(fileobj=sub_buf, mode='w') as sub_tar:
                for member in members:
                    rel_name = os.path.relpath(member.name, f'volumes/{old_name}')
                    if rel_name == '.':
                        continue
                    info = tarfile.TarInfo(name=rel_name)
                    info.size = member.size
                    info.mode = member.mode
                    info.type = member.type
                    if member.isfile():
                        sub_tar.addfile(info, tar.extractfile(member))
                    else:
                        sub_tar.addfile(info)
            docker_ops.import_volume_tar(new_name, sub_buf.getvalue())
    return True
