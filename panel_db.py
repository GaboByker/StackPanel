import json
import os
import re
import sqlite3
from datetime import datetime, timezone

# project_key -> metadata de respaldo/control para los proyectos que ya
# existían antes de que el panel llevara este registro. Se aplica una sola
# vez (solo rellena columnas que sigan vacías), nunca pisa datos existentes.
_KNOWN_PROJECT_META = {
    'social-hub': {'folder': 'html/social-hub', 'containers': ['social-hub']},
    'empires': {'folder': 'html/Empires-Allies', 'containers': ['empires-allies']},
    'social-empires': {'folder': 'html/social-empires', 'containers': ['social-empires']},
    'torres-arquitectura': {
        'folder': 'html/torres-arquitectura',
        'containers': ['torres-arquitectura', 'torres-db'],
    },
    'finanzas-personales': {'folder': 'html/finanzas-personales', 'containers': ['finanzas-personales']},
    'wapicenter': {
        'folder': 'html/WApiCenter',
        'containers': [
            'wapicenter-api', 'wapicenter-frontend', 'wapicenter-postgres',
            'wapicenter-redis', 'wapicenter-worker-1', 'wapicenter-backup',
        ],
        'volumes': [
            'wapicenter_postgres_data', 'wapicenter_redis_data', 'wapicenter_frontend_dist',
            'wapicenter_avatar_uploads', 'wapicenter_postgres_backups',
        ],
    },
    'gemma4-api-manager': {
        'folder': 'html/gemma4-api-manager',
        'containers': ['gemma4-api-manager', 'gemma4-ollama'],
        'volumes': ['gemma4-api-manager_ollama_data'],
    },
    'wanqara-dashboard': {
        'folder': 'html/wanqara-dashboard',
        'containers': ['wanqara-dashboard-frontend-1', 'wanqara-dashboard-backend-1', 'wanqara-dashboard-db-1'],
        'volumes': ['wanqara-dashboard_db_data', 'wanqara-dashboard_upload_data'],
    },
    'limpieza-contactos': {'folder': 'html/limpieza-contactos', 'containers': ['limpieza-contactos']},
}

DOMAIN_RE = re.compile(
    r'^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$'
)
KEY_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
# Hostname/IP para el destino interno de un sitio del proxy (ej. "torres",
# "host.docker.internal", "10.0.0.5"). Deliberadamente estricto: esto se
# inserta tal cual dentro de un archivo .conf de nginx, así que no puede
# llevar espacios, comillas, llaves ni saltos de línea.
TARGET_HOST_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,253}[A-Za-z0-9])?$')

# Dominios y proyectos ya existentes antes de que el panel gestionara esto.
# Se usan solo para poblar la base de datos la primera vez (no se vuelven a
# tocar si las tablas ya tienen datos).
_SEED_SITES = [
    {
        'domain': 'wapicenter.xfirepc.com',
        'target_host': 'host.docker.internal',
        'target_port': 8090,
        'ssl_enabled': 1,
        'managed': 0,
        'notes': 'Config personalizado (app + /api). No se regenera desde el panel.',
    },
    {
        'domain': 'pagina.torresarquitecturaec.com',
        'target_host': 'torres',
        'target_port': 80,
        'ssl_enabled': 1,
        'managed': 0,
        'notes': 'Config personalizado (WordPress). No se regenera desde el panel.',
    },
]

_SEED_PROJECT_OVERRIDES = {
    'wapicenter': {'access_mode': 'domain', 'domain': 'wapicenter.xfirepc.com'},
    'torres-arquitectura': {'access_mode': 'domain', 'domain': 'pagina.torresarquitecturaec.com'},
    'limpieza-contactos': {'port': 5052},
}


def _db_path(root):
    instance = os.path.join(root, 'instance')
    os.makedirs(instance, exist_ok=True)
    return os.path.join(instance, 'portal.db')


def _connect(root):
    conn = sqlite3.connect(_db_path(root))
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_db(root):
    with _connect(root) as conn:
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL UNIQUE COLLATE NOCASE,
                target_host TEXT NOT NULL,
                target_port INTEGER NOT NULL,
                ssl_enabled INTEGER NOT NULL DEFAULT 0,
                managed INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_key TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL,
                description TEXT,
                access_mode TEXT NOT NULL DEFAULT 'port',
                port INTEGER,
                domain TEXT,
                path TEXT NOT NULL DEFAULT '/',
                icon_path TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            '''
        )
        _migrate_projects_columns(conn)
        _seed_sites(conn)
        _seed_projects(conn, root)
        _backfill_known_projects(conn)

        conn.execute(
            'CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)'
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS metrics_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                cpu_percent REAL,
                mem_percent REAL,
                disk_percent REAL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS project_databases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                engine TEXT NOT NULL,
                host TEXT NOT NULL,
                port INTEGER NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                dbname TEXT NOT NULL,
                allow_write INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                admin_email TEXT,
                action TEXT NOT NULL,
                detail TEXT
            )
            '''
        )
        conn.execute(
            '''
            CREATE TABLE IF NOT EXISTS sftp_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                uid INTEGER NOT NULL UNIQUE,
                allow_write INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            '''
        )


def _migrate_projects_columns(conn):
    existing = {row[1] for row in conn.execute('PRAGMA table_info(projects)')}
    additions = {
        'folder': "ALTER TABLE projects ADD COLUMN folder TEXT",
        'containers': "ALTER TABLE projects ADD COLUMN containers TEXT",
        'volumes': "ALTER TABLE projects ADD COLUMN volumes TEXT",
        'template': "ALTER TABLE projects ADD COLUMN template TEXT",
        'secrets': "ALTER TABLE projects ADD COLUMN secrets TEXT",
        'desired_state': "ALTER TABLE projects ADD COLUMN desired_state TEXT NOT NULL DEFAULT 'running'",
        'monitor_health': "ALTER TABLE projects ADD COLUMN monitor_health INTEGER NOT NULL DEFAULT 1",
        'cpu_limit': "ALTER TABLE projects ADD COLUMN cpu_limit REAL",
        'mem_limit_mb': "ALTER TABLE projects ADD COLUMN mem_limit_mb INTEGER",
        'auto_backup': "ALTER TABLE projects ADD COLUMN auto_backup INTEGER NOT NULL DEFAULT 0",
        'backup_retention': "ALTER TABLE projects ADD COLUMN backup_retention INTEGER",
        'backup_days': "ALTER TABLE projects ADD COLUMN backup_days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'",
        'backup_hour': "ALTER TABLE projects ADD COLUMN backup_hour INTEGER NOT NULL DEFAULT 3",
        'last_auto_backup_date': "ALTER TABLE projects ADD COLUMN last_auto_backup_date TEXT",
        'repos': "ALTER TABLE projects ADD COLUMN repos TEXT",
    }
    for column, ddl in additions.items():
        if column not in existing:
            conn.execute(ddl)


def _backfill_known_projects(conn):
    for key, meta in _KNOWN_PROJECT_META.items():
        row = conn.execute(
            'SELECT id, folder, containers FROM projects WHERE project_key = ? COLLATE NOCASE', (key,)
        ).fetchone()
        if not row or row['folder'] or row['containers']:
            continue
        conn.execute(
            'UPDATE projects SET folder = ?, containers = ?, volumes = ? WHERE id = ?',
            (
                meta.get('folder'),
                json.dumps(meta.get('containers') or []),
                json.dumps(meta.get('volumes') or []),
                row['id'],
            ),
        )


def _seed_sites(conn):
    count = conn.execute('SELECT COUNT(*) FROM sites').fetchone()[0]
    if count:
        return
    for site in _SEED_SITES:
        conn.execute(
            '''
            INSERT INTO sites (domain, target_host, target_port, ssl_enabled, managed, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                site['domain'], site['target_host'], site['target_port'],
                site['ssl_enabled'], site['managed'], site['notes'], _now(),
            ),
        )


def _seed_projects(conn, root):
    count = conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
    if count:
        return
    path = os.path.join(root, 'projects.json')
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, list):
        return
    for i, item in enumerate(data):
        key = item.get('id') or f'proyecto-{i}'
        override = _SEED_PROJECT_OVERRIDES.get(key, {})
        access_mode = override.get('access_mode', 'port')
        domain = override.get('domain')
        port = override.get('port', item.get('port'))
        try:
            conn.execute(
                '''
                INSERT INTO projects
                    (project_key, name, description, access_mode, port, domain, path, icon_path, sort_order, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    key,
                    item.get('name', key),
                    item.get('description', ''),
                    access_mode,
                    port,
                    domain,
                    item.get('path') or '/',
                    item.get('icon_path'),
                    i,
                    _now(),
                ),
            )
        except sqlite3.IntegrityError:
            continue


# --- sites ---------------------------------------------------------------

def list_sites(root):
    with _connect(root) as conn:
        rows = conn.execute('SELECT * FROM sites ORDER BY domain').fetchall()
    return [dict(row) for row in rows]


def get_site(root, site_id):
    with _connect(root) as conn:
        row = conn.execute('SELECT * FROM sites WHERE id = ?', (site_id,)).fetchone()
    return dict(row) if row else None


def validate_domain(domain):
    domain = (domain or '').strip().lower()
    if not DOMAIN_RE.match(domain):
        return None, 'Dominio no válido. Usa un formato como midominio.com.'
    return domain, None


def create_site(root, domain, target_host, target_port, project_id=None):
    domain, error = validate_domain(domain)
    if error:
        return None, error
    target_host = (target_host or '').strip()
    if not target_host or not TARGET_HOST_RE.match(target_host):
        return None, 'El destino (host interno) no es válido (solo letras, números, puntos y guiones).'
    try:
        target_port = int(target_port)
        if not (1 <= target_port <= 65535):
            raise ValueError
    except (TypeError, ValueError):
        return None, 'El puerto destino no es válido.'
    try:
        with _connect(root) as conn:
            cur = conn.execute(
                '''
                INSERT INTO sites (domain, target_host, target_port, ssl_enabled, managed, notes, created_at)
                VALUES (?, ?, ?, 0, 1, ?, ?)
                ''',
                (domain, target_host, target_port, f'project:{project_id}' if project_id else None, _now()),
            )
            site_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return None, 'Ya existe un sitio con ese dominio.'
    return get_site(root, site_id), None


def set_site_ssl(root, site_id, enabled):
    with _connect(root) as conn:
        conn.execute('UPDATE sites SET ssl_enabled = ? WHERE id = ?', (1 if enabled else 0, site_id))


def delete_site(root, site_id):
    with _connect(root) as conn:
        conn.execute('DELETE FROM sites WHERE id = ?', (site_id,))


# --- projects --------------------------------------------------------------

def list_projects_raw(root):
    with _connect(root) as conn:
        rows = conn.execute('SELECT * FROM projects ORDER BY sort_order, name').fetchall()
    return [dict(row) for row in rows]


def get_project(root, project_id):
    with _connect(root) as conn:
        row = conn.execute('SELECT * FROM projects WHERE id = ?', (project_id,)).fetchone()
    return dict(row) if row else None


def _slugify(name):
    slug = re.sub(r'[^a-z0-9]+', '-', (name or '').strip().lower()).strip('-')
    return slug[:64] or 'proyecto'


def reserve_key(root, name):
    """Calcula un project_key único a partir de un nombre, sin insertar nada."""
    key = _slugify(name)
    with _connect(root) as conn:
        existing = {row['project_key'] for row in conn.execute('SELECT project_key FROM projects')}
    base_key = key
    n = 2
    while key in existing:
        key = f'{base_key}-{n}'
        n += 1
    return key


def insert_project(root, key, name, description, access_mode, port, domain, path, icon_path,
                    folder=None, containers=None, volumes=None, template=None, secrets=None, repos=None):
    with _connect(root) as conn:
        max_sort = conn.execute('SELECT COALESCE(MAX(sort_order), 0) FROM projects').fetchone()[0]
        cur = conn.execute(
            '''
            INSERT INTO projects
                (project_key, name, description, access_mode, port, domain, path, icon_path,
                 sort_order, created_at, folder, containers, volumes, template, secrets, repos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                key, name, (description or '').strip(), access_mode, port, domain, path,
                (icon_path or '').strip() or None, max_sort + 1, _now(),
                folder, json.dumps(containers or []), json.dumps(volumes or []), template,
                json.dumps(secrets or {}), json.dumps(repos or []),
            ),
        )
        project_id = cur.lastrowid
    return get_project(root, project_id)


def create_project(root, name, description, access_mode, port, domain, path, icon_path):
    name = (name or '').strip()
    if not name:
        return None, 'El nombre es obligatorio.'
    path = (path or '/').strip() or '/'
    if not path.startswith('/'):
        path = '/' + path

    if access_mode == 'domain':
        domain, error = validate_domain(domain)
        if error:
            return None, error
        port = None
    elif access_mode == 'port':
        domain = None
        try:
            port = int(port)
            if not (1 <= port <= 65535):
                raise ValueError
        except (TypeError, ValueError):
            return None, 'El puerto es obligatorio y debe ser un número válido.'
    else:
        return None, 'Modo de acceso no válido.'

    key = reserve_key(root, name)
    project = insert_project(root, key, name, description, access_mode, port, domain, path, icon_path)
    return project, None


def project_containers(project):
    try:
        return json.loads(project.get('containers') or '[]')
    except (TypeError, ValueError):
        return []


def project_volumes(project):
    try:
        return json.loads(project.get('volumes') or '[]')
    except (TypeError, ValueError):
        return []


def project_secrets(project):
    try:
        return json.loads(project.get('secrets') or '{}')
    except (TypeError, ValueError):
        return {}


def project_repos(project):
    try:
        return json.loads(project.get('repos') or '[]')
    except (TypeError, ValueError):
        return []


def delete_project(root, project_id):
    with _connect(root) as conn:
        conn.execute('DELETE FROM projects WHERE id = ?', (project_id,))


def set_desired_state(root, project_id, state):
    with _connect(root) as conn:
        conn.execute('UPDATE projects SET desired_state = ? WHERE id = ?', (state, project_id))


def set_project_folder(root, project_id, folder):
    with _connect(root) as conn:
        conn.execute('UPDATE projects SET folder = ? WHERE id = ?', (folder, project_id))


def set_description(root, project_id, description):
    with _connect(root) as conn:
        conn.execute(
            'UPDATE projects SET description = ? WHERE id = ?',
            ((description or '').strip(), project_id),
        )


def set_monitor_health(root, project_id, enabled):
    with _connect(root) as conn:
        conn.execute('UPDATE projects SET monitor_health = ? WHERE id = ?', (1 if enabled else 0, project_id))


def set_auto_backup(root, project_id, enabled):
    with _connect(root) as conn:
        conn.execute('UPDATE projects SET auto_backup = ? WHERE id = ?', (1 if enabled else 0, project_id))


def set_backup_schedule(root, project_id, enabled, days, hour, retention):
    with _connect(root) as conn:
        conn.execute(
            'UPDATE projects SET auto_backup = ?, backup_days = ?, backup_hour = ?, backup_retention = ? WHERE id = ?',
            (1 if enabled else 0, ','.join(days), hour, retention, project_id),
        )


def set_last_auto_backup_date(root, project_id, date_str):
    with _connect(root) as conn:
        conn.execute('UPDATE projects SET last_auto_backup_date = ? WHERE id = ?', (date_str, project_id))


def set_resource_limits(root, project_id, cpu_limit, mem_limit_mb):
    with _connect(root) as conn:
        conn.execute(
            'UPDATE projects SET cpu_limit = ?, mem_limit_mb = ? WHERE id = ?',
            (cpu_limit, mem_limit_mb, project_id),
        )


# --- settings (clave/valor) --------------------------------------------

def get_setting(root, key, default=None):
    with _connect(root) as conn:
        row = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    return row['value'] if row else default


def get_settings(root, keys):
    with _connect(root) as conn:
        placeholders = ','.join('?' for _ in keys)
        rows = conn.execute(f'SELECT key, value FROM settings WHERE key IN ({placeholders})', keys).fetchall()
    return {row['key']: row['value'] for row in rows}


def set_settings(root, values):
    with _connect(root) as conn:
        for key, value in values.items():
            conn.execute(
                'INSERT INTO settings (key, value) VALUES (?, ?) '
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                (key, value),
            )


# --- historial de métricas ------------------------------------------------

def add_metrics_sample(root, cpu_percent, mem_percent, disk_percent):
    with _connect(root) as conn:
        conn.execute(
            'INSERT INTO metrics_history (ts, cpu_percent, mem_percent, disk_percent) VALUES (?, ?, ?, ?)',
            (_now(), cpu_percent, mem_percent, disk_percent),
        )
        conn.execute(
            "DELETE FROM metrics_history WHERE ts < datetime('now', '-7 days')"
        )


def list_metrics_history(root, hours=24):
    with _connect(root) as conn:
        rows = conn.execute(
            "SELECT * FROM metrics_history WHERE ts >= datetime('now', ?) ORDER BY ts",
            (f'-{hours} hours',),
        ).fetchall()
    return [dict(row) for row in rows]


# --- conexiones de base de datos por proyecto -------------------------------

def list_databases(root, project_id):
    with _connect(root) as conn:
        rows = conn.execute(
            'SELECT * FROM project_databases WHERE project_id = ? ORDER BY id', (project_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_database(root, db_id):
    with _connect(root) as conn:
        row = conn.execute('SELECT * FROM project_databases WHERE id = ?', (db_id,)).fetchone()
    return dict(row) if row else None


def add_database(root, project_id, engine, host, port, username, password, dbname):
    with _connect(root) as conn:
        cur = conn.execute(
            '''
            INSERT INTO project_databases
                (project_id, engine, host, port, username, password, dbname, allow_write, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            ''',
            (project_id, engine, host, port, username, password, dbname, _now()),
        )
        db_id = cur.lastrowid
    return get_database(root, db_id)


def set_database_allow_write(root, db_id, allow_write):
    with _connect(root) as conn:
        conn.execute('UPDATE project_databases SET allow_write = ? WHERE id = ?', (1 if allow_write else 0, db_id))


def delete_database(root, db_id):
    with _connect(root) as conn:
        conn.execute('DELETE FROM project_databases WHERE id = ?', (db_id,))


# --- accesos SFTP por proyecto ----------------------------------------------
# uid arranca en 3000 para no chocar con usuarios/servicios del sistema.
_SFTP_UID_BASE = 3000


def list_sftp_users(root, project_id=None):
    with _connect(root) as conn:
        if project_id is None:
            rows = conn.execute('SELECT * FROM sftp_users ORDER BY username').fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM sftp_users WHERE project_id = ? ORDER BY id', (project_id,)
            ).fetchall()
    return [dict(row) for row in rows]


def get_sftp_user(root, user_id):
    with _connect(root) as conn:
        row = conn.execute('SELECT * FROM sftp_users WHERE id = ?', (user_id,)).fetchone()
    return dict(row) if row else None


def create_sftp_user(root, project_id, username, password_hash):
    with _connect(root) as conn:
        next_uid = conn.execute(
            'SELECT COALESCE(MAX(uid), ?) + 1 FROM sftp_users', (_SFTP_UID_BASE - 1,)
        ).fetchone()[0]
        cur = conn.execute(
            '''
            INSERT INTO sftp_users (project_id, username, password_hash, uid, allow_write, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            ''',
            (project_id, username, password_hash, next_uid, _now()),
        )
        user_id = cur.lastrowid
    return get_sftp_user(root, user_id)


def set_sftp_user_password(root, user_id, password_hash):
    with _connect(root) as conn:
        conn.execute('UPDATE sftp_users SET password_hash = ? WHERE id = ?', (password_hash, user_id))


def set_sftp_user_write(root, user_id, allow_write):
    with _connect(root) as conn:
        conn.execute('UPDATE sftp_users SET allow_write = ? WHERE id = ?', (1 if allow_write else 0, user_id))


def delete_sftp_user(root, user_id):
    with _connect(root) as conn:
        conn.execute('DELETE FROM sftp_users WHERE id = ?', (user_id,))


# --- auditoría --------------------------------------------------------------

def log_action(root, admin_email, action, detail=''):
    with _connect(root) as conn:
        conn.execute(
            'INSERT INTO audit_log (ts, admin_email, action, detail) VALUES (?, ?, ?, ?)',
            (_now(), admin_email, action, detail),
        )


def list_audit(root, limit=200):
    with _connect(root) as conn:
        rows = conn.execute(
            'SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
    return [dict(row) for row in rows]
