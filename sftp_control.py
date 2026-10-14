"""Contenedor SFTP compartido (atmoz/sftp) con un usuario aislado (chroot) por acceso.

La escritura se da igualando el gid del usuario al grupo dueño de la carpeta; la lectura,
montándola en solo lectura. Cambiar un acceso recrea el contenedor y corta todas las sesiones.
"""
import os

import docker_ops
import panel_db

IMAGE = 'atmoz/sftp:alpine'
CONTAINER_NAME = 'stackpanel-sftp'
HOST_KEYS_VOLUME = 'stackpanel-sftp-host-keys'
SFTP_PORT = int(os.environ.get('SFTP_PORT', '2222'))


def folder_group_writable(stack_root, folder):
    """True si el grupo dueño de la carpeta puede escribir; si no, un acceso "rw" no podrá subir nada."""
    try:
        return bool(os.stat(os.path.join(stack_root, folder)).st_mode & 0o020)
    except OSError:
        return False


def _folder_gid(stack_root, folder):
    """gid dueño de la carpeta del proyecto en el host."""
    try:
        return os.stat(os.path.join(stack_root, folder)).st_gid
    except OSError:
        return None


def sync(root, stack_root, host_stack_root):
    """Recrea el contenedor SFTP con los usuarios activos de la base."""
    users = panel_db.list_sftp_users(root)
    if not users:
        docker_ops.remove_container(CONTAINER_NAME)
        return True, ''

    projects_by_id = {p['id']: p for p in panel_db.list_projects_raw(root)}

    docker_ops.ensure_volume(HOST_KEYS_VOLUME)
    ok, err = docker_ops.ensure_image(IMAGE)
    if not ok:
        return False, f'No se pudo descargar la imagen de SFTP: {err}'

    binds = [f'{HOST_KEYS_VOLUME}:/etc/ssh']
    cmd = []
    for user in users:
        project = projects_by_id.get(user['project_id'])
        if not project or not project.get('folder'):
            continue
        gid = _folder_gid(stack_root, project['folder'])
        if gid is None:
            continue
        host_folder = os.path.join(host_stack_root, project['folder'])
        mode = '' if user['allow_write'] else ':ro'
        binds.append(f"{host_folder}:/home/{user['username']}/files{mode}")
        # "e" indica al entrypoint que la contraseña ya viene cifrada (chpasswd -e).
        cmd.append(f"{user['username']}:{user['password_hash']}:e:{user['uid']}:{gid}:files")

    if not cmd:
        docker_ops.remove_container(CONTAINER_NAME)
        return True, ''

    container_id, err = docker_ops.create_container(
        CONTAINER_NAME,
        IMAGE,
        ports={'22/tcp': SFTP_PORT},
        binds=binds,
        cmd=cmd,
    )
    if not container_id:
        return False, err
    return True, ''
