"""Datos propios de UNA instalación concreta (servicios Docker que el panel ya
gestionaba antes de existir el registro de proyectos, proyectos y dominios
iniciales, carpetas de grafos). Viven en instance/site_presets.json, que no se
versiona (instance/ está en .gitignore): el repositorio y el instalador no
llevan datos de ningún servidor, y una instalación nueva arranca vacía.

Formato (todas las claves son opcionales):
  managed_services        {clave: {containers, label, port, health_path, ...}}
  known_project_meta      {project_key: {folder, containers, volumes}}
  seed_sites              [{domain, target_host, target_port, ssl_enabled, managed, notes}]
  seed_project_overrides  {project_key: {access_mode, domain, port}}
  projects                [{id, name, description, port, path, icon_path}]
  graphify_projects       {project_id: carpeta relativa a STACK_ROOT}
"""
import json
import os

PATH = os.environ.get(
    'STACKPANEL_PRESETS',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'site_presets.json'),
)
_cache = None


def load():
    global _cache
    if _cache is None:
        try:
            with open(PATH, encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            data = {}
        _cache = data if isinstance(data, dict) else {}
    return _cache


def get(key, default):
    """Valor de `key` si existe y es del mismo tipo que `default`."""
    value = load().get(key)
    return value if isinstance(value, type(default)) else default
