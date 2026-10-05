import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps

import pyotp
from flask import g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MIN_PASSWORD_LEN = 8

# Sin valor por defecto: si no defines PORTAL_BOOTSTRAP_EMAIL, no se crea
# ningún admin automático — en su lugar, el primer acceso al panel muestra
# el asistente de primera configuración (/setup) para crear la cuenta ahí.
# PORTAL_BOOTSTRAP_EMAIL solo existe para instalaciones automatizadas que
# quieran saltarse el asistente definiendo el admin por variables de entorno.
BOOTSTRAP_EMAIL = os.environ.get('PORTAL_BOOTSTRAP_EMAIL')
BOOTSTRAP_PASSWORD = os.environ.get('PORTAL_BOOTSTRAP_PASSWORD')


def _db_path(root):
    instance = os.path.join(root, 'instance')
    os.makedirs(instance, exist_ok=True)
    return os.path.join(instance, 'portal.db')


def _connect(root):
    conn = sqlite3.connect(_db_path(root))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(root):
    with _connect(root) as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by INTEGER REFERENCES admins(id)
            )
            '''
        )
        existing_cols = {row[1] for row in conn.execute('PRAGMA table_info(admins)')}
        if 'totp_secret' not in existing_cols:
            conn.execute('ALTER TABLE admins ADD COLUMN totp_secret TEXT')
        if 'totp_enabled' not in existing_cols:
            conn.execute('ALTER TABLE admins ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0')
        # session_epoch: subirlo invalida todas las sesiones abiertas de ese admin.
        if 'session_epoch' not in existing_cols:
            conn.execute('ALTER TABLE admins ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0')
        # Último paso TOTP aceptado: impide reutilizar el mismo código.
        if 'totp_last_step' not in existing_cols:
            conn.execute('ALTER TABLE admins ADD COLUMN totp_last_step INTEGER NOT NULL DEFAULT 0')
        count = conn.execute('SELECT COUNT(*) FROM admins').fetchone()[0]
        if count == 0 and BOOTSTRAP_EMAIL:
            password = BOOTSTRAP_PASSWORD or secrets.token_urlsafe(12)
            conn.execute(
                'INSERT INTO admins (email, password_hash, created_at, created_by) VALUES (?, ?, ?, NULL)',
                (
                    BOOTSTRAP_EMAIL.strip().lower(),
                    generate_password_hash(password),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            if BOOTSTRAP_PASSWORD:
                print(f'Portal: admin inicial creado ({BOOTSTRAP_EMAIL})')
            else:
                print(
                    f'Portal: admin inicial creado ({BOOTSTRAP_EMAIL}) '
                    f'con contraseña generada: {password}  '
                    '(cámbiala de inmediato en Administradores > Cambiar mi contraseña)'
                )


def normalize_email(email):
    return (email or '').strip().lower()


def get_admin_id():
    aid = session.get('admin_id')
    if aid is None:
        return None
    try:
        return int(aid)
    except (TypeError, ValueError):
        return None


def get_admin(root):
    aid = get_admin_id()
    if not aid:
        return None
    with _connect(root) as conn:
        row = conn.execute('SELECT id, email, created_at FROM admins WHERE id = ?', (aid,)).fetchone()
    return dict(row) if row else None


# Hash de relleno: si el correo no existe se verifica igual contra esto, para
# que el tiempo de respuesta no delate qué correos son de administradores.
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(16))


def authenticate(root, email, password):
    email = normalize_email(email)
    with _connect(root) as conn:
        row = conn.execute(
            'SELECT id, email, password_hash, totp_enabled FROM admins WHERE email = ? COLLATE NOCASE',
            (email,),
        ).fetchone()
    valid = check_password_hash(row['password_hash'] if row else _DUMMY_HASH, password or '')
    if not row or not valid:
        return None, 'Correo o contraseña incorrectos.'
    return {'id': row['id'], 'email': row['email'], 'totp_enabled': bool(row['totp_enabled'])}, None


def get_totp_state(root, admin_id):
    with _connect(root) as conn:
        row = conn.execute(
            'SELECT totp_secret, totp_enabled FROM admins WHERE id = ?', (admin_id,)
        ).fetchone()
    if not row:
        return None, False
    return row['totp_secret'], bool(row['totp_enabled'])


def set_totp_secret(root, admin_id, secret):
    with _connect(root) as conn:
        conn.execute('UPDATE admins SET totp_secret = ?, totp_enabled = 0 WHERE id = ?', (secret, admin_id))


def verify_totp(root, admin_id, code):
    """Valida un código TOTP (±30 s) y lo marca como usado: el mismo código
    no sirve dos veces aunque siga dentro de su ventana."""
    code = (code or '').strip()
    if not code.isdigit() or len(code) != 6:
        return False
    with _connect(root) as conn:
        row = conn.execute(
            'SELECT totp_secret, totp_last_step FROM admins WHERE id = ?', (admin_id,)
        ).fetchone()
        if not row or not row['totp_secret']:
            return False
        totp = pyotp.TOTP(row['totp_secret'])
        now = datetime.now(timezone.utc)
        for offset in (0, -1, 1):
            moment = now + timedelta(seconds=30 * offset)
            step = totp.timecode(moment)
            if step > row['totp_last_step'] and secrets.compare_digest(totp.at(moment), code):
                conn.execute('UPDATE admins SET totp_last_step = ? WHERE id = ?', (step, admin_id))
                return True
    return False


def confirm_totp(root, admin_id):
    with _connect(root) as conn:
        conn.execute('UPDATE admins SET totp_enabled = 1 WHERE id = ?', (admin_id,))


def disable_totp(root, admin_id):
    with _connect(root) as conn:
        conn.execute('UPDATE admins SET totp_secret = NULL, totp_enabled = 0 WHERE id = ?', (admin_id,))


def change_password(root, admin_id, current_password, new_password):
    with _connect(root) as conn:
        row = conn.execute('SELECT password_hash FROM admins WHERE id = ?', (admin_id,)).fetchone()
        if not row or not check_password_hash(row['password_hash'], current_password or ''):
            return False, 'La contraseña actual no es correcta.'
        if len(new_password or '') < MIN_PASSWORD_LEN:
            return False, f'La contraseña nueva debe tener al menos {MIN_PASSWORD_LEN} caracteres.'
        conn.execute(
            'UPDATE admins SET password_hash = ?, session_epoch = session_epoch + 1 WHERE id = ?',
            (generate_password_hash(new_password), admin_id),
        )
    return True, None


def get_session_epoch(root, admin_id):
    with _connect(root) as conn:
        row = conn.execute('SELECT session_epoch FROM admins WHERE id = ?', (admin_id,)).fetchone()
    return row['session_epoch'] if row else None


def revoke_sessions(root, admin_id=None):
    """Cierra las sesiones abiertas de un admin (o de todos si admin_id es None)."""
    with _connect(root) as conn:
        if admin_id is None:
            conn.execute('UPDATE admins SET session_epoch = session_epoch + 1')
        else:
            conn.execute('UPDATE admins SET session_epoch = session_epoch + 1 WHERE id = ?', (admin_id,))


def login_admin(admin, root):
    now = int(datetime.now(timezone.utc).timestamp())
    session.clear()
    session['admin_id'] = admin['id']
    session['epoch'] = get_session_epoch(root, admin['id'])
    session['auth_at'] = now
    session['seen_at'] = now
    session.permanent = True


def logout_admin():
    session.clear()
    session.modified = True


def list_admins(root):
    with _connect(root) as conn:
        rows = conn.execute(
            '''
            SELECT a.id, a.email, a.created_at, c.email AS created_by_email
            FROM admins a
            LEFT JOIN admins c ON c.id = a.created_by
            ORDER BY a.id
            '''
        ).fetchall()
    return [dict(row) for row in rows]


def create_admin(root, email, password, created_by_id):
    email = normalize_email(email)
    if not EMAIL_RE.match(email):
        return None, 'Correo electrónico no válido.'
    if len(password or '') < MIN_PASSWORD_LEN:
        return None, f'La contraseña debe tener al menos {MIN_PASSWORD_LEN} caracteres.'
    try:
        with _connect(root) as conn:
            conn.execute(
                'INSERT INTO admins (email, password_hash, created_at, created_by) VALUES (?, ?, ?, ?)',
                (
                    email,
                    generate_password_hash(password),
                    datetime.now(timezone.utc).isoformat(),
                    created_by_id,
                ),
            )
    except sqlite3.IntegrityError:
        return None, 'Ya existe un administrador con ese correo.'
    return email, None


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not get_admin_id():
            return redirect(url_for('admin_login', next=request.path))
        g.admin = get_admin(view.__globals__.get('PORTAL_ROOT', ''))
        return view(*args, **kwargs)
    return wrapped
