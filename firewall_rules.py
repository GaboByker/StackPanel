"""Exposición de puertos del servidor, gestionada desde /admin/firewall.

Cada puerto puede ser:
  public      abierto a todo internet (no hay regla: es lo normal)
  restricted  solo entran las IPs/rangos indicados
  closed      solo desde la red interna (Docker, el proxy, el propio servidor)

Las reglas se guardan en settings (fw_ports = confirmadas). Todo cambio se
aplica primero "a prueba" (fw_pending, con un plazo): si el admin no lo
confirma a tiempo, el agente del host vuelve solo a las reglas confirmadas.
Así un error que corte el acceso al panel se deshace sin intervención.

La lista blanca de Seguridad y la de emergencia del servidor siempre entran
a cualquier puerto, y las conexiones ya abiertas no se cortan al cambiar.
"""
import json
from datetime import datetime, timedelta, timezone

import guard_client
import panel_db
import security

CONFIRM_SECONDS = 120
MAX_RULES = 200
POLICIES = {
    'public': 'Público',
    'restricted': 'Solo IPs permitidas',
    'closed': 'Cerrado (solo red interna)',
}
WELL_KNOWN = {
    ('tcp', 22): 'SSH del servidor',
    ('tcp', 53): 'DNS local',
    ('udp', 53): 'DNS local',
}


def _now():
    return datetime.now(timezone.utc)


def _load(root, key, default):
    try:
        value = json.loads(panel_db.get_setting(root, key) or 'null')
    except ValueError:
        return default
    return default if value is None else value


def get_committed(root):
    rules = _load(root, 'fw_ports', [])
    return rules if isinstance(rules, list) else []


def get_pending(root):
    """El cambio a prueba si sigue vigente, o None."""
    pending = _load(root, 'fw_pending', None)
    if not isinstance(pending, dict):
        return None
    try:
        deadline = datetime.fromisoformat(pending['deadline'])
    except (KeyError, TypeError, ValueError):
        return None
    if deadline <= _now():
        return None
    pending['seconds_left'] = int((deadline - _now()).total_seconds())
    return pending


def expire_if_needed(root):
    """Limpia un cambio a prueba vencido (el agente ya lo revirtió en el
    kernel). Devuelve True si había uno, para avisar en pantalla."""
    pending = _load(root, 'fw_pending', None)
    if not isinstance(pending, dict):
        return False
    if get_pending(root):
        return False
    panel_db.set_settings(root, {'fw_pending': ''})
    panel_db.log_action(
        root, None, 'fw_reverted',
        f'Cambio de {pending.get("by") or "?"} no confirmado a tiempo: se volvió a las reglas anteriores',
    )
    return True


def effective(root):
    pending = get_pending(root)
    return pending['rules'] if pending else get_committed(root)


def parse_form(form):
    """Filas port_N/proto_N/policy_N/allow_N/note_N -> lista de reglas no
    públicas. Devuelve (reglas, error)."""
    rules, seen = [], set()
    indexes = sorted({k.split('_', 1)[1] for k in form if k.startswith('port_')})
    for idx in indexes:
        raw_port = (form.get(f'port_{idx}') or '').strip()
        if not raw_port:
            continue
        try:
            port = int(raw_port)
        except ValueError:
            return None, f'Puerto no válido: {raw_port}'
        proto = form.get(f'proto_{idx}', 'tcp')
        policy = form.get(f'policy_{idx}', 'public')
        if not 1 <= port <= 65535 or proto not in ('tcp', 'udp') or policy not in POLICIES:
            return None, f'Regla no válida para el puerto {raw_port}.'
        if (proto, port) in seen:
            return None, f'El puerto {port}/{proto} aparece dos veces.'
        seen.add((proto, port))
        if policy == 'public':
            continue
        allow = []
        if policy == 'restricted':
            for token in (form.get(f'allow_{idx}') or '').replace(',', '\n').split():
                cidr = security.parse_network(token)
                if not cidr:
                    return None, f'{port}/{proto}: "{token}" no es una IP o rango válido.'
                allow.append(cidr)
            if not allow:
                return None, f'{port}/{proto}: "Solo IPs permitidas" necesita al menos una IP o rango.'
        rules.append({
            'proto': proto, 'port': port, 'policy': policy, 'allow': allow,
            'note': (form.get(f'note_{idx}') or '').strip()[:120],
        })
    if len(rules) > MAX_RULES:
        return None, f'Máximo {MAX_RULES} reglas.'
    return rules, None


def lockout_error(root, rules, admin_ip, panel_port, static_allow):
    """Rechaza cambios que, de entrada, dejarían fuera al admin del SSH o del
    panel. (El plazo de confirmación cubre lo que esto no pueda prever.)"""
    trusted = [r['cidr'] for r in security.list_allowlist(root)] + list(static_allow or [])
    if security._in_any(admin_ip, trusted):
        return None
    protected = {('tcp', 22): 'SSH', ('tcp', panel_port): 'el panel'}
    for rule in rules:
        what = protected.get((rule['proto'], rule['port']))
        if not what:
            continue
        if rule['policy'] == 'closed' or not security._in_any(admin_ip, rule['allow']):
            return (
                f'Cerrar o restringir {rule["port"]}/{rule["proto"]} te dejaría sin acceso a {what} '
                f'desde tu IP ({admin_ip}). Agrega tu IP a las permitidas de ese puerto o a la lista '
                'blanca en Seguridad.'
            )
    return None


def propose(root, rules, admin_email):
    deadline = _now() + timedelta(seconds=CONFIRM_SECONDS)
    panel_db.set_settings(root, {'fw_pending': json.dumps({
        'rules': rules, 'deadline': deadline.isoformat(), 'by': admin_email,
    })})
    guard_client.request_sync()


def confirm(root):
    pending = get_pending(root)
    if not pending:
        return False
    panel_db.set_settings(root, {'fw_ports': json.dumps(pending['rules']), 'fw_pending': ''})
    guard_client.request_sync()
    return True


def revert(root):
    panel_db.set_settings(root, {'fw_pending': ''})
    guard_client.request_sync()


def describe(rules):
    if not rules:
        return 'todos los puertos públicos'
    parts = []
    for r in rules:
        if r['policy'] == 'closed':
            parts.append(f'{r["port"]}/{r["proto"]} cerrado')
        else:
            parts.append(f'{r["port"]}/{r["proto"]} solo {", ".join(r["allow"])}')
    return '; '.join(parts)


def port_table(root, published, listening):
    """Filas para la pantalla: puertos publicados por Docker, puertos del
    host y cualquier puerto que ya tenga regla, con su regla vigente.
    published: [{port, proto, container}]; listening: [{port, proto}]."""
    projects = panel_db.list_projects_raw(root)
    by_port = {p['port']: p['name'] for p in projects if p.get('port')}
    by_container = {}
    for p in projects:
        for c in panel_db.project_containers(p):
            by_container[c] = p['name']
    rows = {}
    for item in published:
        key = (item['proto'], item['port'])
        label = by_container.get(item['container']) or by_port.get(item['port'])
        desc = f'{label} ({item["container"]})' if label else f'Contenedor {item["container"]}'
        rows.setdefault(key, {'proto': key[0], 'port': key[1], 'what': desc, 'docker': True})
    for item in listening:
        key = (item['proto'], item['port'])
        if key not in rows:
            rows[key] = {
                'proto': key[0], 'port': key[1], 'docker': False,
                'what': WELL_KNOWN.get(key) or by_port.get(key[1]) or 'Servicio del servidor',
            }
    rules = {(r['proto'], r['port']): r for r in effective(root)}
    for key, rule in rules.items():
        rows.setdefault(key, {'proto': key[0], 'port': key[1], 'what': 'Sin servicio detectado', 'docker': False})
    out = []
    for key, row in rows.items():
        rule = rules.get(key)
        row['policy'] = rule['policy'] if rule else 'public'
        row['allow'] = rule.get('allow', []) if rule else []
        row['note'] = rule.get('note', '') if rule else ''
        out.append(row)
    out.sort(key=lambda r: (r['port'], r['proto']))
    return out

