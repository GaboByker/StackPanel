import os
import re
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MIN_PASSWORD_LEN = 8

BOOTSTRAP_EMAIL = os.environ.get('PORTAL_BOOTSTRAP_EMAIL', 'darkblood1977@gmail.com')
BOOTSTRAP_PASSWORD = os.environ.get('PORTAL_BOOTSTRAP_PASSWORD', '03197546')


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
        count = conn.execute('SELECT COUNT(*) FROM admins').fetchone()[0]
        if count == 0 and BOOTSTRAP_EMAIL and BOOTSTRAP_PASSWORD:
            conn.execute(
                'INSERT INTO admins (email, password_hash, created_at, created_by) VALUES (?, ?, ?, NULL)',
                (
                    BOOTSTRAP_EMAIL.strip().lower(),
                    generate_password_hash(BOOTSTRAP_PASSWORD),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            print(f'Portal: admin inicial creado ({BOOTSTRAP_EMAIL})')


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


def authenticate(root, email, password):
    email = normalize_email(email)
    with _connect(root) as conn:
        row = conn.execute(
            'SELECT id, email, password_hash FROM admins WHERE email = ? COLLATE NOCASE',
            (email,),
        ).fetchone()
    if not row or not check_password_hash(row['password_hash'], password or ''):
        return None, 'Correo o contraseña incorrectos.'
    return {'id': row['id'], 'email': row['email']}, None


def login_admin(admin):
    session.clear()
    session['admin_id'] = admin['id']
    session.permanent = True


def logout_admin():
    session.pop('admin_id', None)


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
