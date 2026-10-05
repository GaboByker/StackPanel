#!/usr/bin/env python3
"""stackpanel-guard: agente del host que lleva los bloqueos del panel al
firewall del kernel (nftables).

Separación de privilegios:
  - El panel (expuesto a internet, dentro de Docker) NO tiene permisos de
    red. Solo guarda en su base de datos qué IPs bloquear y cuáles permitir.
  - Este agente (root, en el host, sin red) lee esa base en modo solo
    lectura, valida cada entrada y aplica el resultado en su propia tabla
    `inet stackpanel`. Nunca ejecuta texto que venga del panel: solo IPs que
    pasan por ipaddress.ip_network.
  - El panel le habla por un socket Unix: "sync" y "status" para el
    firewall, y "ssh_sessions" / "ssh_terminate" para ver y cerrar sesiones
    SSH del host (ver sessions.py; solo por Id validado).

Diseño de la tabla:
  - Cadena en prerouting con prioridad -300: corre antes del conntrack y del
    DNAT de Docker, así que cubre los puertos del host Y los publicados por
    contenedores (que UFW no ve), en IPv4 e IPv6.
  - Sets con rangos y caducidad: el kernel quita solo cada bloqueo al
    vencer, aunque el agente esté parado.
  - Si el agente se cae, las reglas siguen en el kernel (falla seguro).

Protección contra dejarse fuera:
  - /etc/stackpanel-guard/allow.conf: lista blanca que solo root puede
    editar. El panel no puede tocarla. Siempre se acepta antes de bloquear.
  - Nunca se bloquean redes no públicas (loopback, privadas, Docker...), ni
    las IPs del propio servidor, ni rangos más amplios que MIN_PREFIX_V4/V6.
  - Interruptor de emergencia: `touch /etc/stackpanel-guard/disabled`
    retira la tabla en el siguiente ciclo y la deja retirada (sobrevive a
    reinicios) hasta borrar ese archivo.
"""
import argparse
import hashlib
import ipaddress
import json
import logging
import math
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone

import detector as detector_mod
import sessions as sessions_mod

VERSION = '4'
TABLE = 'stackpanel'
CONF_DIR = '/etc/stackpanel-guard'
CONF_FILE = os.path.join(CONF_DIR, 'guard.conf')
ALLOW_FILE = os.path.join(CONF_DIR, 'allow.conf')
DISABLED_FLAG = os.path.join(CONF_DIR, 'disabled')
SOCKET_PATH = '/run/stackpanel-guard/guard.sock'
NFT = '/usr/sbin/nft'
# El kernel guarda la caducidad en ms en 32 bits (~49 días). Los bloqueos
# más largos se cargan con este tope y se renuevan con REFRESH_SECONDS.
MAX_ELEMENT_TIMEOUT = 30 * 86400
# Reaplicación completa periódica aunque no haya cambios: renueva los topes
# de arriba y repara la tabla si alguien la tocó a mano.
REFRESH_SECONDS = 3600
# Exposición de puertos: tráfico de redes internas (Docker, el propio
# servidor, la red privada del proveedor) nunca se filtra por puerto, para
# que el proxy y los contenedores sigan llegando a un puerto "cerrado".
INTERNAL4 = ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', '169.254.0.0/16']
INTERNAL6 = ['fc00::/7', 'fe80::/10']
MAX_PORT_RULES = 200
SSH_PORT = 22

DEFAULTS = {
    'DB_PATH': '',
    'POLL_SECONDS': '10',
    'MIN_PREFIX_V4': '16',
    'MIN_PREFIX_V6': '48',
}

log = logging.getLogger('stackpanel-guard')


# --- configuración ------------------------------------------------------------

def load_config():
    conf = dict(DEFAULTS)
    try:
        with open(CONF_FILE) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                conf[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return conf


def load_static_allow():
    nets, errors = [], []
    try:
        with open(ALLOW_FILE) as fh:
            for raw in fh:
                line = raw.split('#', 1)[0].strip()
                if not line:
                    continue
                try:
                    nets.append(ipaddress.ip_network(line, strict=False))
                except ValueError:
                    errors.append(line)
    except FileNotFoundError:
        pass
    return nets, errors


def host_addresses():
    """IPs configuradas en las interfaces del servidor."""
    try:
        out = subprocess.run(['ip', '-j', 'addr'], capture_output=True, text=True, timeout=5).stdout
        addrs = set()
        for iface in json.loads(out or '[]'):
            for info in iface.get('addr_info', []):
                try:
                    addrs.add(ipaddress.ip_address(info['local']))
                except (KeyError, ValueError):
                    continue
        return addrs
    except Exception:
        return set()


# --- estado deseado -----------------------------------------------------------

def _parse_ts(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_db(db_path):
    """(bans, allow, jails, globals) desde la base del panel, solo lectura."""
    uri = 'file:' + db_path + '?mode=ro'
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        jails, globals_ = detector_mod.load_jails(conn)
        now = datetime.now(timezone.utc).isoformat()
        bans = conn.execute(
            'SELECT cidr, expires_at, source, reason FROM ip_bans '
            'WHERE lifted_at IS NULL AND (expires_at IS NULL OR expires_at > ?)',
            (now,),
        ).fetchall()
        allow = [r[0] for r in conn.execute('SELECT cidr FROM ip_allowlist').fetchall()]
        fw = dict(conn.execute(
            "SELECT key, value FROM settings WHERE key IN ('fw_ports', 'fw_pending')"
        ).fetchall())
    finally:
        conn.close()
    return bans, allow, jails, globals_, fw


def effective_port_rules(fw, static_allow):
    """Reglas de exposición vigentes. Si hay un cambio a prueba (fw_pending)
    y no venció su plazo, se aplica ese; al vencer sin confirmar se vuelve
    solo a lo confirmado (fw_ports). La reversión la hace el agente, no el
    panel: funciona aunque el cambio te haya dejado sin acceso al panel.
    -> (reglas, 'pending'|'committed', plazo|None, omitidas)"""
    now = datetime.now(timezone.utc)
    version, deadline = 'committed', None
    try:
        raw = json.loads(fw.get('fw_ports') or '[]')
    except ValueError:
        raw = []
    try:
        pending = json.loads(fw.get('fw_pending') or 'null')
    except ValueError:
        pending = None
    if isinstance(pending, dict):
        try:
            pending_deadline = _parse_ts(pending.get('deadline'))
        except ValueError:
            pending_deadline = None
        if pending_deadline and pending_deadline > now:
            raw, version, deadline = pending.get('rules') or [], 'pending', pending_deadline
    rules, skipped, seen = [], [], set()
    for item in raw[:MAX_PORT_RULES] if isinstance(raw, list) else []:
        try:
            proto = item['proto']
            port = int(item['port'])
            policy = item['policy']
        except (KeyError, TypeError, ValueError):
            continue
        if proto not in ('tcp', 'udp') or not 1 <= port <= 65535 or policy not in ('restricted', 'closed'):
            continue
        if (proto, port) in seen:
            continue
        seen.add((proto, port))
        if proto == 'tcp' and port == SSH_PORT and not static_allow:
            skipped.append({'cidr': f'{proto}/{port}',
                            'reason': 'no se restringe SSH sin IPs en /etc/stackpanel-guard/allow.conf'})
            continue
        nets = []
        for cidr in item.get('allow') or []:
            try:
                nets.append(ipaddress.ip_network(str(cidr), strict=False))
            except ValueError:
                continue
        rules.append({
            'proto': proto, 'port': port, 'policy': policy,
            'allow4': list(ipaddress.collapse_addresses(n for n in nets if n.version == 4)) if policy == 'restricted' else [],
            'allow6': list(ipaddress.collapse_addresses(n for n in nets if n.version == 6)) if policy == 'restricted' else [],
        })
    return rules, version, deadline, skipped


def listening_ports():
    """Puertos escuchando en el host hacia afuera (no solo en localhost)."""
    try:
        out = subprocess.run(['ss', '-Hltun'], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    found = set()
    for line in out.splitlines():
        cols = line.split()
        if len(cols) < 5:
            continue
        proto, local = cols[0], cols[4]
        addr, _, port = local.rpartition(':')
        addr = addr.strip('[]').split('%')[0]
        if addr.startswith('127.') or addr == '::1' or not port.isdigit():
            continue
        found.add((proto, int(port)))
    return [{'proto': p, 'port': n} for p, n in sorted(found, key=lambda x: (x[1], x[0]))]


def _merge_nested(entries):
    """Los sets con rangos no aceptan elementos solapados. Dos CIDR o son
    disjuntos o uno contiene al otro: se queda el mayor con la caducidad más
    lejana (None = permanente gana)."""
    kept = []
    for net, expires in sorted(entries, key=lambda e: (e[0].version, e[0].prefixlen)):
        parent = next((k for k in kept if k[0].version == net.version and net.subnet_of(k[0])), None)
        if parent is None:
            kept.append([net, expires])
        elif parent[1] is not None and (expires is None or expires > parent[1]):
            parent[1] = expires
    return [(n, e) for n, e in kept]


def build_desired(conf, bans, db_allow, static_allow):
    min_v4 = int(conf['MIN_PREFIX_V4'])
    min_v6 = int(conf['MIN_PREFIX_V6'])
    own = host_addresses()
    skipped = []
    ban_entries = []
    for cidr, expires_at, source, reason in bans:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            skipped.append({'cidr': cidr, 'reason': 'no es una IP o rango válido'})
            continue
        if not net.is_global:
            skipped.append({'cidr': str(net), 'reason': 'red no pública (privada, local o reservada)'})
            continue
        if net.prefixlen < (min_v4 if net.version == 4 else min_v6):
            limit = min_v4 if net.version == 4 else min_v6
            skipped.append({'cidr': str(net), 'reason': f'rango demasiado amplio (mínimo /{limit})'})
            continue
        if any(addr in net for addr in own):
            skipped.append({'cidr': str(net), 'reason': 'incluye una IP de este servidor'})
            continue
        try:
            expires = _parse_ts(expires_at)
        except ValueError:
            expires = None
        ban_entries.append((net, expires))

    allow_nets = list(static_allow)
    for cidr in db_allow:
        try:
            allow_nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            continue

    bans_merged = _merge_nested(ban_entries)
    return {
        'ban4': [(n, e) for n, e in bans_merged if n.version == 4],
        'ban6': [(n, e) for n, e in bans_merged if n.version == 6],
        'allow4': list(ipaddress.collapse_addresses(n for n in allow_nets if n.version == 4)),
        'allow6': list(ipaddress.collapse_addresses(n for n in allow_nets if n.version == 6)),
        'skipped': skipped,
    }


def desired_hash(desired):
    key = json.dumps({
        **{
            k: sorted(str(x) for x in v) if k.startswith('allow')
            else sorted(f'{n}|{e.isoformat() if e else "-"}' for n, e in v)
            for k, v in desired.items() if k in ('allow4', 'allow6', 'ban4', 'ban6')
        },
        'ports': [
            [r['proto'], r['port'], r['policy'], [str(n) for n in r['allow4'] + r['allow6']]]
            for r in desired.get('ports', [])
        ],
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()


# --- nftables -----------------------------------------------------------------

def _nft(args, stdin=None):
    return subprocess.run([NFT] + args, input=stdin, capture_output=True, text=True, timeout=20)


def table_present():
    return _nft(['list', 'table', 'inet', TABLE]).returncode == 0


def existing_port_sets():
    res = _nft(['-j', 'list', 'sets', 'table', 'inet', TABLE])
    if res.returncode != 0:
        return set()
    return {
        item['set']['name'] for item in json.loads(res.stdout).get('nftables', [])
        if 'set' in item and item['set']['name'].startswith('r_')
    }


def render(desired, stale_sets=()):
    """Una sola transacción: crea lo que falte (add es idempotente), rehace
    las reglas y reemplaza el contenido de los sets. O se aplica todo o nada."""
    now = datetime.now(timezone.utc)
    t = f'inet {TABLE}'
    lines = [
        f'add table {t}',
        f'add set {t} allow4 {{ type ipv4_addr; flags interval; }}',
        f'add set {t} allow6 {{ type ipv6_addr; flags interval; }}',
        f'add set {t} ban4 {{ type ipv4_addr; flags interval, timeout; }}',
        f'add set {t} ban6 {{ type ipv6_addr; flags interval, timeout; }}',
        # Contadores con nombre: sobreviven a cada reaplicación de reglas.
        f'add counter {t} dropped4',
        f'add counter {t} dropped6',
        f'add chain {t} prerouting {{ type filter hook prerouting priority -300; policy accept; }}',
        f'flush chain {t} prerouting',
        f'add rule {t} prerouting iif "lo" accept',
        f'add rule {t} prerouting ip saddr @allow4 accept',
        f'add rule {t} prerouting ip6 saddr @allow6 accept',
        f'add rule {t} prerouting ip saddr @ban4 counter name dropped4 drop',
        f'add rule {t} prerouting ip6 saddr @ban6 counter name dropped6 drop',
    ]
    for name in ('allow4', 'allow6', 'ban4', 'ban6'):
        lines.append(f'flush set {t} {name}')
    for name in ('allow4', 'allow6'):
        if desired[name]:
            lines.append(f'add element {t} {name} {{ ' + ', '.join(str(n) for n in desired[name]) + ' }')
    for name in ('ban4', 'ban6'):
        elems = []
        for net, expires in desired[name]:
            if expires is None:
                elems.append(str(net))
            else:
                remaining = min(math.ceil((expires - now).total_seconds()), MAX_ELEMENT_TIMEOUT)
                if remaining > 0:
                    elems.append(f'{net} timeout {remaining}s')
        if elems:
            lines.append(f'add element {t} {name} {{ ' + ', '.join(elems) + ' }')

    # Exposición por puerto. Va en otra cadena con prioridad -150: después
    # del conntrack (-200), para dejar pasar conexiones ya establecidas y las
    # respuestas a conexiones salientes, y antes del DNAT de Docker (-100),
    # así que el puerto que se ve es el publicado, no el del contenedor.
    lines += [
        f'add set {t} internal4 {{ type ipv4_addr; flags interval; }}',
        f'add set {t} internal6 {{ type ipv6_addr; flags interval; }}',
        f'flush set {t} internal4',
        f'flush set {t} internal6',
        f'add element {t} internal4 {{ ' + ', '.join(INTERNAL4) + ' }',
        f'add element {t} internal6 {{ ' + ', '.join(INTERNAL6) + ' }',
        f'add counter {t} port_drops',
        f'add chain {t} ports {{ type filter hook prerouting priority -150; policy accept; }}',
        f'flush chain {t} ports',
        f'add rule {t} ports ct state established,related accept',
        f'add rule {t} ports iif "lo" accept',
        f'add rule {t} ports ip saddr @allow4 accept',
        f'add rule {t} ports ip6 saddr @allow6 accept',
        f'add rule {t} ports ip saddr @internal4 accept',
        f'add rule {t} ports ip6 saddr @internal6 accept',
    ]
    wanted_sets = set()
    for rule in desired.get('ports', []):
        match = f'meta l4proto {rule["proto"]} th dport {rule["port"]}'
        if rule['policy'] == 'restricted':
            for fam, ver in (('ip', '4'), ('ip6', '6')):
                name = f'r_{rule["proto"]}_{rule["port"]}_{ver}'
                wanted_sets.add(name)
                addr_type = 'ipv4_addr' if ver == '4' else 'ipv6_addr'
                lines += [
                    f'add set {t} {name} {{ type {addr_type}; flags interval; }}',
                    f'flush set {t} {name}',
                ]
                nets = rule['allow' + ver]
                if nets:
                    lines.append(f'add element {t} {name} {{ ' + ', '.join(str(n) for n in nets) + ' }')
                lines.append(f'add rule {t} ports {match} {fam} saddr @{name} accept')
        lines.append(f'add rule {t} ports {match} counter name port_drops drop')
    for name in sorted(set(stale_sets) - wanted_sets):
        lines.append(f'delete set {t} {name}')
    return '\n'.join(lines) + '\n'


def apply_ruleset(text):
    with tempfile.NamedTemporaryFile('w', suffix='.nft', delete=False) as fh:
        fh.write(text)
        path = fh.name
    try:
        check = _nft(['-c', '-f', path])
        if check.returncode != 0:
            return False, check.stderr.strip()
        res = _nft(['-f', path])
        if res.returncode != 0:
            return False, res.stderr.strip()
        return True, ''
    finally:
        os.unlink(path)


def remove_table():
    if table_present():
        _nft(['delete', 'table', 'inet', TABLE])


def kernel_stats():
    res = _nft(['-j', 'list', 'table', 'inet', TABLE])
    if res.returncode != 0:
        return None
    stats = {'ban4': 0, 'ban6': 0, 'allow4': 0, 'allow6': 0, 'dropped_packets': 0, 'dropped_bytes': 0,
             'port_drop_packets': 0}
    for item in json.loads(res.stdout).get('nftables', []):
        if 'set' in item and item['set']['name'] in stats:
            stats[item['set']['name']] = len(item['set'].get('elem', []))
        if 'counter' in item and item['counter']['name'] in ('dropped4', 'dropped6'):
            stats['dropped_packets'] += item['counter'].get('packets', 0)
            stats['dropped_bytes'] += item['counter'].get('bytes', 0)
        if 'counter' in item and item['counter']['name'] == 'port_drops':
            stats['port_drop_packets'] = item['counter'].get('packets', 0)
    return stats


# --- motor --------------------------------------------------------------------

class Guard:
    def __init__(self):
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.last_hash = None
        self.last_apply = 0.0
        self.next_deadline = None
        # Listas que consulta el detector desde sus hilos; se reemplazan
        # enteras (nunca se mutan), así que leerlas no necesita el lock.
        self.allow_nets = []
        self.ban_nets = []
        self.recent_bans = set()
        self.detector = detector_mod.Detector(self)
        self.state = {
            'version': VERSION,
            'started_at': datetime.now(timezone.utc).isoformat(),
            'last_sync': None,
            'last_change': None,
            'last_error': None,
            'disabled': False,
            'skipped': [],
            'static_allow': [],
            'static_allow_errors': [],
        }

    def sync(self, force=False):
        with self.lock:
            conf = load_config()
            static_allow, static_errors = load_static_allow()
            self.state['static_allow'] = [str(n) for n in static_allow]
            self.state['static_allow_errors'] = static_errors
            if os.path.exists(DISABLED_FLAG):
                if not self.state['disabled']:
                    log.warning('interruptor de emergencia activo (%s): tabla retirada', DISABLED_FLAG)
                remove_table()
                self.state['disabled'] = True
                self.last_hash = None
                return True, 'desactivado'
            self.state['disabled'] = False
            self.state['last_error'] = None
            if not conf['DB_PATH']:
                return self._fail('DB_PATH no está definido en ' + CONF_FILE)
            try:
                if self.detector.flush(conf['DB_PATH']):
                    force = True
            except Exception as exc:
                self._fail(f'no se pudieron guardar los eventos detectados: {exc}')
            try:
                bans, db_allow, jails, globals_, fw = read_db(conf['DB_PATH'])
            except Exception as exc:
                # Sin datos nuevos se mantiene lo que ya está en el kernel.
                return self._fail(f'no se pudo leer la base del panel: {exc}')
            desired = build_desired(conf, bans, db_allow, static_allow)
            ports, port_version, port_deadline, port_skipped = effective_port_rules(fw, static_allow)
            desired['ports'] = ports
            desired['skipped'] += port_skipped
            self.next_deadline = port_deadline
            self.state['ports'] = {
                'version': port_version,
                'deadline': port_deadline.isoformat() if port_deadline else None,
                'rules': [
                    {'proto': r['proto'], 'port': r['port'], 'policy': r['policy'],
                     'allow': [str(n) for n in r['allow4'] + r['allow6']]}
                    for r in ports
                ],
            }
            self.state['skipped'] = desired['skipped']
            self.allow_nets = desired['allow4'] + desired['allow6']
            self.ban_nets = [n for n, _ in desired['ban4'] + desired['ban6']]
            self.recent_bans = set()
            self.detector.configure(jails, globals_)
            digest = desired_hash(desired)
            fresh = time.monotonic() - self.last_apply < REFRESH_SECONDS
            if not force and fresh and digest == self.last_hash and table_present():
                self.state['last_sync'] = datetime.now(timezone.utc).isoformat()
                return True, 'sin cambios'
            ok, err = apply_ruleset(render(desired, existing_port_sets()))
            if not ok:
                return self._fail(f'nft rechazó el conjunto de reglas: {err}')
            self.last_hash = digest
            self.last_apply = time.monotonic()
            now = datetime.now(timezone.utc).isoformat()
            self.state.update(last_sync=now, last_change=now, last_error=None)
            log.info(
                'aplicado: %d bloqueos v4, %d v6, %d permitidos, %d omitidos',
                len(desired['ban4']), len(desired['ban6']),
                len(desired['allow4']) + len(desired['allow6']), len(desired['skipped']),
            )
            return True, 'aplicado'

    @staticmethod
    def _contains(nets, ip):
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in n for n in nets if n.version == addr.version)

    def is_allowed(self, ip):
        return self._contains(self.allow_nets, ip)

    def is_banned(self, ip):
        return ip in self.recent_bans or self._contains(self.ban_nets, ip)

    def mark_banned(self, ip):
        self.recent_bans = self.recent_bans | {ip}
        self.wake.set()

    def _fail(self, message):
        self.state['last_error'] = message
        log.error(message)
        return False, message

    def status(self):
        with self.lock:
            data = dict(self.state)
        data['table_present'] = table_present()
        data['kernel'] = kernel_stats()
        data['jails'] = self.detector.status()
        data['listening'] = listening_ports()
        return data

    def loop(self):
        while True:
            try:
                self.sync()
                self.detector.save_state()
            except Exception as exc:
                self._fail(f'error inesperado: {exc}')
            interval = max(2, int(load_config().get('POLL_SECONDS', '10') or 10))
            if self.next_deadline:
                # Despertar justo al vencer un cambio a prueba, para revertirlo a tiempo.
                left = (self.next_deadline - datetime.now(timezone.utc)).total_seconds() + 0.5
                interval = max(0.5, min(interval, left))
            self.wake.wait(interval)
            self.wake.clear()


def serve_socket(guard):
    os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o660)
    srv.listen(8)

    def handle(conn):
        with conn:
            conn.settimeout(5)
            try:
                raw = conn.recv(4096)
                req = json.loads(raw.decode() or '{}')
                cmd = req.get('cmd')
                if cmd == 'sync':
                    ok, msg = guard.sync()
                    reply = {'ok': ok, 'message': msg}
                elif cmd == 'status':
                    reply = {'ok': True, 'status': guard.status()}
                elif cmd == 'ssh_sessions':
                    reply = {'ok': True, 'sessions': sessions_mod.list_sessions()}
                elif cmd == 'ssh_terminate':
                    ok, msg = sessions_mod.terminate(req.get('id'))
                    if ok:
                        log.info('panel: %s', msg)
                    reply = {'ok': ok, 'message': msg}
                elif cmd == 'ping':
                    reply = {'ok': True, 'version': VERSION}
                else:
                    reply = {'ok': False, 'message': 'orden desconocida'}
            except Exception as exc:
                reply = {'ok': False, 'message': str(exc)}
            try:
                conn.sendall(json.dumps(reply).encode() + b'\n')
            except OSError:
                pass

    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def client(cmd):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(30)
    sock.connect(SOCKET_PATH)
    sock.sendall(json.dumps({'cmd': cmd}).encode())
    data = b''
    while not data.endswith(b'\n'):
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    return json.loads(data.decode())


def main():
    parser = argparse.ArgumentParser(description='Agente de firewall de StackPanel')
    parser.add_argument('command', choices=['run', 'sync', 'status', 'show', 'flush'])
    args = parser.parse_args()

    if args.command == 'run':
        logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s', stream=sys.stdout)
        guard = Guard()
        threading.Thread(target=serve_socket, args=(guard,), daemon=True).start()
        log.info('stackpanel-guard v%s iniciado', VERSION)
        guard.loop()
    elif args.command in ('sync', 'status'):
        print(json.dumps(client(args.command), indent=2, ensure_ascii=False))
    elif args.command == 'show':
        os.execv(NFT, [NFT, 'list', 'table', 'inet', TABLE])
    elif args.command == 'flush':
        # Retira la tabla ahora. Si el servicio sigue activo la volverá a
        # crear en el siguiente ciclo: para dejarla retirada usa el archivo
        # /etc/stackpanel-guard/disabled.
        remove_table()
        print('Tabla inet stackpanel retirada.')


if __name__ == '__main__':
    main()
