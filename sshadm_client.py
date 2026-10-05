"""Cliente de stackpanel-sshadm (usuarios, claves y sshd del host) por
socket Unix. El panel no toca /etc ni /home: le pide cada cambio al agente,
que valida todo por su cuenta (ver guard/stackpanel_sshadm.py)."""
import json
import os
import socket

SOCKET_PATH = os.environ.get('SSHADM_SOCKET', '/run/stackpanel-sshadm/sshadm.sock')


def _call(cmd, timeout, **args):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(SOCKET_PATH)
        sock.sendall(json.dumps({'cmd': cmd, **args}).encode() + b'\n')
        data = b''
        while not data.endswith(b'\n'):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        return json.loads(data.decode() or '{}')
    finally:
        sock.close()


def status(timeout=20):
    """(status_dict, error). error es un texto si el agente no respondió."""
    try:
        reply = _call('status', timeout)
    except (OSError, ValueError) as exc:
        return None, str(exc)
    if not reply.get('ok'):
        return None, reply.get('message') or 'respuesta inválida del agente'
    return reply.get('status'), None


def run(cmd, timeout=60, **args):
    """(ok, mensaje) de una orden de cambio."""
    try:
        reply = _call(cmd, timeout, **args)
    except (OSError, ValueError) as exc:
        return False, f'el agente stackpanel-sshadm no respondió ({exc})'
    return bool(reply.get('ok')), reply.get('message', '')
