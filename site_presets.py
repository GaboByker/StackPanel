"""Datos propios de una instalación, en instance/site_presets.json (no se versiona).

Claves opcionales para sembrar la base:
  known_project_meta      {project_key: {folder, containers, volumes}}
  seed_sites              [{domain, target_host, target_port, ssl_enabled, managed, notes}]
  seed_project_overrides  {project_key: {access_mode, domain, port}}
  projects                [{id, name, description, port, path, icon_path}]
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
