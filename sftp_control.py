"""Contenedor SFTP compartido (atmoz/sftp): un usuario aislado (chroot) por
cada acceso que se crea desde un proyecto, sin tocar el código cada vez.

Cada usuario ve únicamente la carpeta de SU proyecto (no puede ni saber que
existen los demás). El permiso de escritura se controla igualando el grupo
(gid) del usuario al dueño real de la carpeta en el host (que ya es
group-writable) para "rw", o montando la carpeta en modo solo-lectura para
"ro" — no se toca el dueño de ningún archivo existente.

Como el bind de cada usuario es fijo al crear el contenedor, agregar/quitar/
cambiar un acceso recrea el contenedor entero (pocos segundos, tira las
sesiones SFTP activas de todos los proyectos, no solo la que cambió).
"""
import os

import docker_ops
import panel_db

IMAGE = 'atmoz/sftp:alpine'
CONTAINER_NAME = 'stackpanel-sftp'
HOST_KEYS_VOLUME = 'stackpanel-sftp-host-keys'
SFTP_PORT = int(os.environ.get('SFTP_PORT', '2222'))


def folder_group_writable(stack_root, folder):
    """True si el grupo dueño de la carpeta tiene permiso de escritura (así
    es como se le da "escritura" a un acceso SFTP: no se toca el dueño de
    ningún archivo). Si la carpeta es de root y no es group-writable (p.ej.
    quedó creada por un contenedor corriendo como root), un acceso SFTP con
    "escritura" no va a poder subir nada aunque el toggle diga que sí."""
    try:
        return bool(os.stat(os.path.join(stack_root, folder)).st_mode & 0o020)
    except OSError:
        return False


def _folder_gid(stack_root, folder):
    """gid dueño de la carpeta del proyecto en el host, para que un usuario
    con ese mismo gid pueda escribir ahí (ya es group-writable)."""
    try:
        return os.stat(os.path.join(stack_root, folder)).st_gid
    except OSError:
        return None


def sync(root, stack_root, host_stack_root):
    """Recrea el contenedor SFTP con los usuarios activos en la base de
    datos. Se llama después de crear/borrar/editar cualquier acceso."""
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
        # El campo "e" le dice al entrypoint que password_hash ya viene
        # encriptado (chpasswd -e); si no, lo tomaría como texto plano.
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
