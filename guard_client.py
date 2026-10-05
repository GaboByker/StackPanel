"""Cliente del agente del host (stackpanel-guard) por socket Unix.

El panel no tiene permisos sobre el firewall: solo le avisa al agente que
hubo cambios ("sync") y le pide su estado ("status"). Si el agente no está
instalado o no responde, el panel sigue funcionando igual (los bloqueos
quedan en la base y el agente los aplica al volver; además relee la base
cada pocos segundos por su cuenta)."""
import json
import os
import socket
import threading

SOCKET_PATH = os.environ.get('GUARD_SOCKET', '/run/stackpanel-guard/guard.sock')


def _call(cmd, timeout):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(SOCKET_PATH)
        sock.sendall(json.dumps({'cmd': cmd}).encode())
        data = b''
        while not data.endswith(b'\n'):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        return json.loads(data.decode() or '{}')
    finally:
        sock.close()


def status(timeout=3):
    """(status_dict, error). error es un texto si el agente no respondió."""
    try:
        reply = _call('status', timeout)
    except (OSError, ValueError) as exc:
        return None, str(exc)
    if not reply.get('ok'):
        return None, reply.get('message') or 'respuesta inválida del agente'
    return reply.get('status'), None


def sync(timeout=10):
    try:
        reply = _call('sync', timeout)
    except (OSError, ValueError) as exc:
        return False, str(exc)
    return bool(reply.get('ok')), reply.get('message', '')


def request_sync():
    """Aviso en segundo plano: no frena la petición web que lo dispara."""
    threading.Thread(target=sync, daemon=True).start()
