#!/usr/bin/env python3
"""stackpanel-sshadm: agente del host que administra el acceso SSH a pedido
del panel: usuarios del sistema, sus claves autorizadas, su contraseña,
el grupo sudo y la configuración de sshd.

Va aparte de stackpanel-guard a propósito: el guard solo toca el firewall y
corre casi sin permisos; este necesita escribir en /etc y /home, así que
tiene su propio servicio, su propio socket y sus propias reglas.

Reglas que el panel no puede saltarse (se comprueban aquí, no en el panel):
  - Solo se administran cuentas normales (UID 1000-59999). root nunca.
  - Los usuarios de PROTECTED_USERS (el admin que instaló esto) no se pueden
    borrar ni quitar de sudo.
  - Ningún cambio puede dejar el servidor sin al menos un usuario con sudo
    capaz de entrar por SSH con la configuración vigente.
  - Las claves nuevas se validan con ssh-keygen y no se aceptan opciones
    (command=, from=...). Se escriben sin seguir enlaces simbólicos.
  - La configuración de sshd va en un archivo propio
    (/etc/ssh/sshd_config.d/05-stackpanel.conf, que gana a los demás),
    se valida con `sshd -t` y se aplica A PRUEBA: si no se confirma en
    CONFIRM_SECONDS, el agente vuelve solo a la anterior. Las conexiones
    ya abiertas no se cortan al recargar sshd.

Kill switch: `touch /etc/stackpanel-sshadm/disabled` hace que el agente
rechace todas las órdenes de cambio (solo responde al estado).
"""
import grp
import json
import logging
import os
import pwd
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

VERSION = '1'
SOCKET_PATH = '/run/stackpanel-sshadm/sshadm.sock'
CONF_FILE = '/etc/stackpanel-sshadm/sshadm.conf'
DISABLED_FLAG = '/etc/stackpanel-sshadm/disabled'
STATE_FILE = '/var/lib/stackpanel-sshadm/state.json'
DROPIN = '/etc/ssh/sshd_config.d/05-stackpanel.conf'
CONFIRM_SECONDS = 300
SUDO_GROUP = 'sudo'
UID_MIN, UID_MAX = 1000, 59999
MAX_KEYS = 50
MIN_PASSWORD = 12

SSHD = '/usr/sbin/sshd'
SSH_KEYGEN = '/usr/bin/ssh-keygen'
SYSTEMCTL = '/usr/bin/systemctl'
LOGINCTL = '/usr/bin/loginctl'
USERADD = '/usr/sbin/useradd'
USERDEL = '/usr/sbin/userdel'
GPASSWD = '/usr/bin/gpasswd'
CHPASSWD = '/usr/sbin/chpasswd'
_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}

USER_RE = re.compile(r'^[a-z_][a-z0-9_-]{0,31}$')
KEY_TYPES = (
    'ssh-ed25519', 'ssh-rsa', 'ecdsa-sha2-nistp256', 'ecdsa-sha2-nistp384', 'ecdsa-sha2-nistp521',
    'sk-ssh-ed25519@openssh.com', 'sk-ecdsa-sha2-nistp256@openssh.com',
)
FP_RE = re.compile(r'^SHA256:[A-Za-z0-9+/]{43}$')

# Ajustes de sshd que se pueden cambiar desde el panel y sus valores válidos.
SSHD_SETTINGS = {
    'PermitRootLogin': ('yes', 'prohibit-password', 'no'),
    'PasswordAuthentication': ('yes', 'no'),
    'MaxAuthTries': tuple(str(n) for n in range(1, 11)),
    'X11Forwarding': ('yes', 'no'),
}

log = logging.getLogger('stackpanel-sshadm')


class Refused(Exception):
    """Orden rechazada: el mensaje se muestra tal cual en el panel."""


def _run(args, stdin=None, timeout=30):
    res = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=timeout, env=_ENV)
    return res.returncode, (res.stdout or '').strip(), (res.stderr or '').strip()


def _now():
    return datetime.now(timezone.utc)


def load_conf():
    conf = {'PROTECTED_USERS': ''}
    try:
        with open(CONF_FILE) as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    conf[k.strip()] = v.strip()
    except OSError:
        pass
    conf['protected'] = {u for u in re.split(r'[\s,]+', conf['PROTECTED_USERS']) if u}
    return conf


# --- usuarios -----------------------------------------------------------------

def _managed_pw(name):
    """pwd de una cuenta administrable, o Refused."""
    if not USER_RE.match(name or ''):
        raise Refused('Nombre de usuario no válido')
    try:
        pw = pwd.getpwnam(name)
    except KeyError:
        raise Refused(f'El usuario {name} no existe')
    if not UID_MIN <= pw.pw_uid <= UID_MAX:
        raise Refused(f'{name} es una cuenta del sistema: no se administra desde el panel')
    return pw


def _sudo_members():
    try:
        return set(grp.getgrnam(SUDO_GROUP).gr_mem)
    except KeyError:
        return set()


def _password_state(name):
    """'set' | 'locked' | 'none'. Lee /etc/shadow (solo el campo de la clave)."""
    try:
        with open('/etc/shadow') as fh:
            for line in fh:
                parts = line.split(':')
                if parts[0] == name:
                    h = parts[1] if len(parts) > 1 else ''
                    if not h or h in ('*', '!', '!!', '!*'):
                        return 'none'
                    return 'locked' if h.startswith('!') else 'set'
    except OSError:
        pass
    return 'none'


def _open_ssh_dir(pw, create):
    """fd de ~/.ssh, comprobando dueño y sin seguir enlaces. None si no existe."""
    home_fd = os.open(pw.pw_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(home_fd).st_uid != pw.pw_uid:
            raise Refused(f'La carpeta {pw.pw_dir} no pertenece a {pw.pw_name}')
        if create:
            try:
                os.mkdir('.ssh', 0o700, dir_fd=home_fd)
            except FileExistsError:
                pass
        try:
            fd = os.open('.ssh', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=home_fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise Refused(f'{pw.pw_dir}/.ssh no es una carpeta normal')
        st = os.fstat(fd)
        if st.st_uid not in (pw.pw_uid, 0):
            os.close(fd)
            raise Refused(f'{pw.pw_dir}/.ssh no pertenece a {pw.pw_name}')
        if create:
            os.fchown(fd, pw.pw_uid, pw.pw_gid)
            os.fchmod(fd, 0o700)
        return fd
    finally:
        os.close(home_fd)


def _read_key_lines(pw):
    fd = _open_ssh_dir(pw, create=False)
    if fd is None:
        return []
    try:
        try:
            kfd = os.open('authorized_keys', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        except FileNotFoundError:
            return []
        except OSError:
            raise Refused('authorized_keys no es un archivo normal')
        with os.fdopen(kfd, 'r', errors='replace') as fh:
            return fh.read(256 * 1024).splitlines()
    finally:
        os.close(fd)


def _write_key_lines(pw, lines):
    fd = _open_ssh_dir(pw, create=True)
    try:
        tmp = f'.authorized_keys.{secrets.token_hex(6)}'
        kfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(kfd, 'w') as fh:
                fh.write(''.join(line + '\n' for line in lines))
                fh.flush()
                os.fchown(fh.fileno(), pw.pw_uid, pw.pw_gid)
                os.fsync(fh.fileno())
            os.rename(tmp, 'authorized_keys', src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=fd)
            except OSError:
                pass
            raise
    finally:
        os.close(fd)


def _fingerprint(line):
    """(fingerprint, bits, tipo, comentario) de una línea de authorized_keys, o None."""
    code, out, _ = _run([SSH_KEYGEN, '-l', '-E', 'sha256', '-f', '-'], stdin=line + '\n', timeout=10)
    if code != 0 or not out:
        return None
    # "256 SHA256:xxxx comentario (ED25519)"
    m = re.match(r'^(\d+) (SHA256:\S+) ?(.*) \(([^)]+)\)$', out.splitlines()[0])
    if not m:
        return None
    # ssh-keygen escapa lo que no es ASCII ("port\\303\\241til"): se deshace.
    comment = re.sub(rb'\\([0-7]{3})', lambda x: bytes([int(x[1], 8)]), m[3].encode()).decode('utf-8', 'replace')
    return m[2], int(m[1]), m[4], comment


def _list_keys(pw):
    keys = []
    for line in _read_key_lines(pw):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        fp = _fingerprint(s)
        if fp:
            has_options = s.split(None, 1)[0] not in KEY_TYPES
            keys.append({'fingerprint': fp[0], 'bits': fp[1], 'type': fp[2], 'comment': fp[3][:120],
                         'options': has_options})
    return keys


def _sshd_effective():
    code, out, err = _run([SSHD, '-T'], timeout=15)
    if code != 0:
        raise RuntimeError(err or 'sshd -T falló')
    values = {}
    for line in out.splitlines():
        k, _, v = line.partition(' ')
        values[k] = v
    return values


def _can_login(user, sshd):
    """¿Puede este usuario entrar por SSH con la configuración dada?"""
    by_key = user['keys'] > 0 and sshd.get('pubkeyauthentication', 'yes') == 'yes'
    by_pass = user['password'] == 'set' and sshd.get('passwordauthentication') == 'yes'
    return by_key or by_pass


def list_users():
    sudo = _sudo_members()
    users = []
    for pw in sorted(pwd.getpwall(), key=lambda p: p.pw_uid):
        if not UID_MIN <= pw.pw_uid <= UID_MAX or not USER_RE.match(pw.pw_name):
            continue
        try:
            keys = _list_keys(pw)
            keys_error = None
        except (Refused, OSError) as exc:
            keys, keys_error = [], str(exc)
        users.append({
            'name': pw.pw_name, 'uid': pw.pw_uid, 'home': pw.pw_dir, 'shell': pw.pw_shell,
            'sudo': pw.pw_name in sudo, 'password': _password_state(pw.pw_name),
            'keys': len(keys), 'key_list': keys, 'keys_error': keys_error,
        })
    return users


def _check_admin_access(users, sshd, action):
    """Que quede al menos un usuario con sudo que pueda entrar."""
    ok = [u['name'] for u in users if u['sudo'] and _can_login(u, sshd)]
    if not ok:
        raise Refused(
            f'{action} dejaría el servidor sin ningún usuario con sudo que pueda entrar por SSH. '
            'Primero agrega una clave o contraseña a otro usuario con sudo.'
        )


def _simulate(name, **changes):
    """Lista de usuarios como quedaría tras el cambio (para comprobar)."""
    users = [dict(u) for u in list_users()]
    if changes.get('delete'):
        return [u for u in users if u['name'] != name]
    for u in users:
        if u['name'] == name:
            u.update({k: v for k, v in changes.items()})
    return users


def _parse_new_key(text, label):
    text = (text or '').strip().replace('\r', '')
    if '\n' in text:
        raise Refused('Pega una sola clave por vez (una línea)')
    parts = text.split()
    if len(parts) < 2 or parts[0] not in KEY_TYPES:
        raise Refused('No parece una clave pública SSH (debe empezar por ssh-ed25519, ssh-rsa, ecdsa-…). '
                      'Pega el contenido del archivo .pub, nunca la clave privada.')
    if not re.fullmatch(r'[A-Za-z0-9+/=]+', parts[1]) or len(parts[1]) > 16384:
        raise Refused('El cuerpo de la clave no es válido')
    label = re.sub(r'[^\w .@:+-]', '', (label or '').strip())[:80] or (
        re.sub(r'[^\w .@:+-]', '', ' '.join(parts[2:]))[:80])
    line = f'{parts[0]} {parts[1]}' + (f' {label}' if label else '')
    fp = _fingerprint(line)
    if not fp:
        raise Refused('ssh-keygen no reconoce la clave')
    if fp[2] == 'RSA' and fp[1] < 2048:
        raise Refused('Las claves RSA de menos de 2048 bits no son seguras')
    return line, fp[0]


def add_key(name, key, label):
    pw = _managed_pw(name)
    line, fp = _parse_new_key(key, label)
    lines = _read_key_lines(pw)
    existing = _list_keys(pw)
    if any(k['fingerprint'] == fp for k in existing):
        raise Refused('Esa clave ya está autorizada para este usuario')
    if len(existing) >= MAX_KEYS:
        raise Refused(f'Máximo {MAX_KEYS} claves por usuario')
    _write_key_lines(pw, lines + [line])
    return f'Clave {fp} agregada a {name}'


def remove_key(name, fingerprint):
    pw = _managed_pw(name)
    if not FP_RE.match(fingerprint or ''):
        raise Refused('Huella no válida')
    lines = _read_key_lines(pw)
    keep, removed = [], 0
    for line in lines:
        s = line.strip()
        fp = _fingerprint(s) if s and not s.startswith('#') else None
        if fp and fp[0] == fingerprint:
            removed += 1
            continue
        keep.append(line)
    if not removed:
        raise Refused('Esa clave ya no está')
    current = next(u for u in list_users() if u['name'] == name)
    _check_admin_access(_simulate(name, keys=current['keys'] - removed), _sshd_effective(),
                        'Quitar esa clave')
    _write_key_lines(pw, keep)
    return f'Clave {fingerprint} quitada de {name}'


def _validate_password(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise Refused(f'La contraseña debe tener al menos {MIN_PASSWORD} caracteres')
    if len(password) > 256 or any(c in password for c in ':\n\r\0'):
        raise Refused('La contraseña tiene caracteres no permitidos (:, saltos de línea)')


def set_password(name, password):
    _managed_pw(name)
    _validate_password(password)
    code, _, err = _run([CHPASSWD], stdin=f'{name}:{password}\n')
    if code != 0:
        raise Refused(f'chpasswd falló: {err}')
    return f'Contraseña de {name} cambiada'


def set_sudo(name, enabled, conf):
    _managed_pw(name)
    if not enabled and name in conf['protected']:
        raise Refused(f'{name} es el administrador principal del servidor: no se le quita sudo')
    if enabled:
        code, _, err = _run([GPASSWD, '-a', name, SUDO_GROUP])
    else:
        _check_admin_access(_simulate(name, sudo=False), _sshd_effective(), f'Quitar sudo a {name}')
        code, _, err = _run([GPASSWD, '-d', name, SUDO_GROUP])
    if code != 0:
        raise Refused(err or 'gpasswd falló')
    return f'{name} {"ahora tiene" if enabled else "ya no tiene"} sudo'


def create_user(name, sudo, password, key, label):
    if not USER_RE.match(name or ''):
        raise Refused('Nombre no válido: minúsculas, números, _ o -, empezando por letra (máx. 32)')
    try:
        pwd.getpwnam(name)
        raise Refused(f'Ya existe un usuario {name}')
    except KeyError:
        pass
    try:
        grp.getgrnam(name)
        raise Refused(f'Ya existe un grupo {name}; elige otro nombre')
    except KeyError:
        pass
    if password:
        _validate_password(password)
    line = _parse_new_key(key, label)[0] if key else None
    if not password and not line:
        raise Refused('Indica una clave SSH, una contraseña o ambas: si no, el usuario no podrá entrar')
    if sudo and not password:
        raise Refused('Un usuario con sudo necesita contraseña (sudo la pide)')
    code, _, err = _run([USERADD, '-m', '-U', '-s', '/bin/bash', '-K', f'UID_MIN={UID_MIN}',
                         '-K', f'UID_MAX={UID_MAX}', name])
    if code != 0:
        raise Refused(f'useradd falló: {err}')
    try:
        pw = pwd.getpwnam(name)
        if password:
            set_password(name, password)
        if line:
            _write_key_lines(pw, [line])
        if sudo:
            code, _, err = _run([GPASSWD, '-a', name, SUDO_GROUP])
            if code != 0:
                raise Refused(err or 'gpasswd falló')
    except BaseException:
        _run([USERDEL, '-r', name])
        raise
    return f'Usuario {name} creado' + (' con sudo' if sudo else '')


def delete_user(name, remove_home, conf):
    pw = _managed_pw(name)
    if name in conf['protected']:
        raise Refused(f'{name} es el administrador principal del servidor: no se puede borrar')
    _check_admin_access(_simulate(name, delete=True), _sshd_effective(), f'Borrar a {name}')
    # Cierra sus sesiones y procesos; si no, userdel se niega.
    _run([LOGINCTL, 'terminate-user', name], timeout=15)
    for _ in range(10):
        code, out, _ = _run(['/usr/bin/pgrep', '-u', str(pw.pw_uid)])
        if code != 0:
            break
        time.sleep(0.5)
    else:
        _run(['/usr/bin/pkill', '-KILL', '-u', str(pw.pw_uid)])
        time.sleep(1)
    args = [USERDEL] + (['-r'] if remove_home else []) + [name]
    code, _, err = _run(args)
    # userdel -r devuelve 12 si no pudo borrar el buzón: no es grave.
    if code not in (0, 12):
        raise Refused(f'userdel falló: {err}')
    return f'Usuario {name} borrado' + (' junto con su carpeta' if remove_home else f' (su carpeta {pw.pw_dir} se conserva)')


# --- configuración de sshd (a prueba) -----------------------------------------

class SshdConfig:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = self._load()

    @staticmethod
    def _load():
        try:
            with open(STATE_FILE) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _save(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w') as fh:
            json.dump(self.state, fh)
        os.replace(tmp, STATE_FILE)

    @staticmethod
    def _read_dropin():
        try:
            with open(DROPIN) as fh:
                return fh.read()
        except FileNotFoundError:
            return None

    @staticmethod
    def _write_dropin(content):
        if content is None:
            try:
                os.unlink(DROPIN)
            except FileNotFoundError:
                pass
            return
        tmp = DROPIN + '.tmp'
        with open(tmp, 'w') as fh:
            fh.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, DROPIN)

    @staticmethod
    def _apply_and_reload(content):
        """Escribe el archivo, valida con sshd -t y recarga. Si no valida,
        lo deja como estaba y lanza Refused."""
        previous = SshdConfig._read_dropin()
        SshdConfig._write_dropin(content)
        code, _, err = _run([SSHD, '-t'], timeout=15)
        if code != 0:
            SshdConfig._write_dropin(previous)
            raise Refused(f'sshd rechazó la configuración: {err}')
        code, _, err = _run([SYSTEMCTL, 'reload', 'ssh'], timeout=30)
        if code != 0:
            SshdConfig._write_dropin(previous)
            _run([SYSTEMCTL, 'reload', 'ssh'], timeout=30)
            raise Refused(f'No se pudo recargar sshd: {err}')

    @staticmethod
    def render(settings):
        lines = [
            '# Administrado por StackPanel (/admin/ssh). No lo edites a mano:',
            '# el panel lo reescribe. Para anularlo, borra este archivo y',
            '# ejecuta: sudo systemctl reload ssh',
        ]
        lines += [f'{k} {settings[k]}' for k in SSHD_SETTINGS if k in settings]
        return '\n'.join(lines) + '\n'

    def managed(self):
        """Ajustes que fija hoy nuestro archivo."""
        content = self._read_dropin() or ''
        out = {}
        for line in content.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0] in SSHD_SETTINGS:
                out[parts[0]] = parts[1]
        return out

    def pending(self):
        p = self.state.get('pending')
        if not p:
            return None
        left = (datetime.fromisoformat(p['deadline']) - _now()).total_seconds()
        return {**{k: v for k, v in p.items() if k != 'previous'}, 'seconds_left': max(0, int(left))}

    def propose(self, settings):
        clean = {}
        for k, allowed in SSHD_SETTINGS.items():
            v = str(settings.get(k, '')).strip()
            if v not in allowed:
                raise Refused(f'Valor no válido para {k}')
            clean[k] = v
        with self.lock:
            if self.state.get('pending'):
                raise Refused('Ya hay un cambio a prueba: confírmalo o descártalo primero')
            # Comprobar el acceso con la configuración nueva.
            sim = dict(_sshd_effective())
            sim['passwordauthentication'] = clean['PasswordAuthentication']
            users = list_users()
            _check_admin_access(users, sim, 'Esta configuración')
            if clean['PermitRootLogin'] != 'yes' and not any(u['sudo'] and _can_login(u, sim) for u in users):
                raise Refused('Sin un usuario con sudo que pueda entrar, no se puede cerrar el acceso de root')
            previous = self._read_dropin()
            content = self.render(clean)
            if content == previous:
                raise Refused('No hay cambios respecto a la configuración actual')
            self._apply_and_reload(content)
            now = _now()
            self.state['pending'] = {
                'applied_at': now.isoformat(),
                'deadline': (now + timedelta(seconds=CONFIRM_SECONDS)).isoformat(),
                'settings': clean,
                'previous': previous,
            }
            self._save()
        return 'Configuración aplicada a prueba'

    def confirm(self):
        with self.lock:
            if not self.state.get('pending'):
                raise Refused('No hay ningún cambio a prueba')
            self.state.pop('pending')
            self._save()
        return 'Configuración de SSH confirmada'

    def revert(self, reason='descartado'):
        with self.lock:
            p = self.state.get('pending')
            if not p:
                raise Refused('No hay ningún cambio a prueba')
            self._apply_and_reload(p.get('previous'))
            self.state.pop('pending')
            self.state['last_revert'] = {'at': _now().isoformat(), 'reason': reason}
            self._save()
        log.warning('configuración de sshd revertida (%s)', reason)
        return 'Se volvió a la configuración anterior de SSH'

    def tick(self):
        p = self.state.get('pending')
        if p and datetime.fromisoformat(p['deadline']) <= _now():
            try:
                self.revert('no se confirmó a tiempo')
            except Exception as exc:
                log.error('no se pudo revertir sshd: %s', exc)


# --- servidor -----------------------------------------------------------------

def status(sshd_conf, conf):
    try:
        effective = _sshd_effective()
        sshd_error = None
    except Exception as exc:
        effective, sshd_error = {}, str(exc)
    return {
        'version': VERSION,
        'disabled': os.path.exists(DISABLED_FLAG),
        'users': list_users(),
        'protected': sorted(conf['protected']),
        'sudo_group': SUDO_GROUP,
        'sshd': {k: effective.get(k.lower()) for k in SSHD_SETTINGS},
        'sshd_extra': {k: effective.get(k) for k in ('port', 'pubkeyauthentication', 'kbdinteractiveauthentication')},
        'sshd_error': sshd_error,
        'managed': sshd_conf.managed(),
        'pending': sshd_conf.pending(),
        'last_revert': sshd_conf.state.get('last_revert'),
        'confirm_seconds': CONFIRM_SECONDS,
        'min_password': MIN_PASSWORD,
    }


def dispatch(req, sshd_conf):
    conf = load_conf()
    cmd = req.get('cmd')
    if cmd == 'ping':
        return {'ok': True, 'version': VERSION}
    if cmd == 'status':
        return {'ok': True, 'status': status(sshd_conf, conf)}
    if os.path.exists(DISABLED_FLAG):
        raise Refused(f'Gestión desactivada en el servidor ({DISABLED_FLAG})')
    s = lambda k: str(req.get(k) or '')
    if cmd == 'add_key':
        msg = add_key(s('user'), s('key'), s('label'))
    elif cmd == 'remove_key':
        msg = remove_key(s('user'), s('fingerprint'))
    elif cmd == 'set_password':
        msg = set_password(s('user'), req.get('password'))
    elif cmd == 'set_sudo':
        msg = set_sudo(s('user'), bool(req.get('enabled')), conf)
    elif cmd == 'create_user':
        msg = create_user(s('user'), bool(req.get('sudo')), req.get('password') or None, s('key'), s('label'))
    elif cmd == 'delete_user':
        msg = delete_user(s('user'), bool(req.get('remove_home')), conf)
    elif cmd == 'sshd_propose':
        msg = sshd_conf.propose(req.get('settings') or {})
    elif cmd == 'sshd_confirm':
        msg = sshd_conf.confirm()
    elif cmd == 'sshd_revert':
        msg = sshd_conf.revert()
    else:
        return {'ok': False, 'message': 'orden desconocida'}
    log.info('panel: %s', msg)
    return {'ok': True, 'message': msg}


def serve(sshd_conf):
    os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o660)
    srv.listen(8)
    # Las órdenes se atienden de a una: nada de dos useradd a la vez.
    busy = threading.Lock()

    def handle(conn):
        with conn:
            conn.settimeout(10)
            try:
                raw = b''
                while len(raw) < 65536:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
                    if raw.endswith(b'\n'):
                        break
                req = json.loads(raw.decode() or '{}')
                with busy:
                    reply = dispatch(req, sshd_conf)
            except Refused as exc:
                reply = {'ok': False, 'message': str(exc)}
            except Exception as exc:
                log.exception('error atendiendo una orden')
                reply = {'ok': False, 'message': f'error interno: {exc}'}
            try:
                conn.sendall(json.dumps(reply).encode() + b'\n')
            except OSError:
                pass

    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s', stream=sys.stdout)
    sshd_conf = SshdConfig()
    threading.Thread(target=serve, args=(sshd_conf,), daemon=True).start()
    log.info('stackpanel-sshadm v%s iniciado', VERSION)
    while True:
        sshd_conf.tick()
        time.sleep(2)


if __name__ == '__main__':
    main()
