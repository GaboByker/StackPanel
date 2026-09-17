"""Explorador y editor básico de archivos, restringido a html/ (los
proyectos). No da acceso al código del panel ni a nada fuera de esa carpeta."""
import os
import shutil

MAX_EDIT_SIZE = 2 * 1024 * 1024  # 2 MiB
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp', '.bmp', '.svgz',
    '.pdf', '.zip', '.tar', '.gz', '.7z', '.rar',
    '.pyc', '.so', '.dll', '.exe', '.db', '.sqlite', '.sqlite3',
    '.woff', '.woff2', '.ttf', '.eot', '.mp3', '.mp4', '.mov', '.avi',
}


class PathError(ValueError):
    pass


def html_root(stack_root):
    dedicated = os.environ.get('HTML_ROOT', '/app/html-rw')
    if os.path.isdir(dedicated):
        return dedicated
    return os.path.join(stack_root, 'html')


def safe_join(stack_root, rel_path):
    root = os.path.realpath(html_root(stack_root))
    rel_path = (rel_path or '').strip('/')
    target = os.path.realpath(os.path.join(root, rel_path))
    if target != root and not target.startswith(root + os.sep):
        raise PathError('Ruta fuera de html/.')
    return target


def list_dir(stack_root, rel_path):
    abs_path = safe_join(stack_root, rel_path)
    if not os.path.isdir(abs_path):
        raise PathError('No es un directorio.')
    entries = []
    for name in sorted(os.listdir(abs_path)):
        full = os.path.join(abs_path, name)
        try:
            stat = os.stat(full)
        except OSError:
            continue
        entries.append({
            'name': name,
            'is_dir': os.path.isdir(full),
            'size': stat.st_size,
            'mtime': stat.st_mtime,
        })
    entries.sort(key=lambda e: (not e['is_dir'], e['name'].lower()))
    return entries


def is_editable(rel_path):
    ext = os.path.splitext(rel_path)[1].lower()
    return ext not in BINARY_EXTENSIONS


def read_file(stack_root, rel_path):
    abs_path = safe_join(stack_root, rel_path)
    if not os.path.isfile(abs_path):
        raise PathError('No es un archivo.')
    if not is_editable(rel_path):
        raise PathError('Este tipo de archivo no se puede editar aquí.')
    size = os.path.getsize(abs_path)
    if size > MAX_EDIT_SIZE:
        raise PathError(f'Archivo demasiado grande para editar ({size // 1024} KB, máximo 2 MB).')
    with open(abs_path, 'rb') as fh:
        raw = fh.read()
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        raise PathError('El archivo no parece texto (no es UTF-8).')


def write_file(stack_root, rel_path, content):
    abs_path = safe_join(stack_root, rel_path)
    if os.path.isdir(abs_path):
        raise PathError('No es un archivo.')
    with open(abs_path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(content)


def delete_file(stack_root, rel_path):
    abs_path = safe_join(stack_root, rel_path)
    if not os.path.isfile(abs_path):
        raise PathError('No es un archivo.')
    os.remove(abs_path)


def delete_dir(stack_root, rel_path):
    abs_path = safe_join(stack_root, rel_path)
    root = os.path.realpath(html_root(stack_root))
    if abs_path == root:
        raise PathError('No se puede eliminar la carpeta raíz de proyectos.')
    if not os.path.isdir(abs_path):
        raise PathError('No es una carpeta.')
    shutil.rmtree(abs_path)


def parent_of(rel_path):
    rel_path = (rel_path or '').strip('/')
    if not rel_path or '/' not in rel_path:
        return ''
    return rel_path.rsplit('/', 1)[0]
