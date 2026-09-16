"""Visor de base de datos por proyecto (tipo mini phpMyAdmin): listar
tablas, ver filas, correr consultas. Soporta MySQL/MariaDB y Postgres.
Solo-lectura por defecto; cada conexión tiene su propia casilla para
permitir escritura."""
import re

SAFE_IDENT_RE = re.compile(r'^[A-Za-z0-9_]+$')
_WRITE_RE = re.compile(r'^\s*(insert|update|delete|drop|alter|create|truncate|grant|revoke)\b', re.IGNORECASE)


def _connect(db):
    engine = db['engine']
    if engine == 'mysql':
        import pymysql
        return pymysql.connect(
            host=db['host'], port=int(db['port']), user=db['username'],
            password=db['password'], database=db['dbname'], connect_timeout=10,
        )
    if engine == 'postgres':
        import psycopg2
        return psycopg2.connect(
            host=db['host'], port=int(db['port']), user=db['username'],
            password=db['password'], dbname=db['dbname'], connect_timeout=10,
        )
    raise ValueError('Motor de base de datos no soportado.')


def test_connection(db):
    try:
        conn = _connect(db)
        conn.close()
        return True, ''
    except Exception as exc:
        return False, str(exc)


def list_tables(db):
    try:
        conn = _connect(db)
    except Exception as exc:
        return [], str(exc)
    try:
        cur = conn.cursor()
        if db['engine'] == 'mysql':
            cur.execute('SHOW TABLES')
        else:
            cur.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        return [row[0] for row in cur.fetchall()], ''
    except Exception as exc:
        return [], str(exc)
    finally:
        conn.close()


def browse_table(db, table, limit=100):
    if not SAFE_IDENT_RE.match(table or ''):
        return None, None, 'Nombre de tabla inválido.'
    try:
        conn = _connect(db)
    except Exception as exc:
        return None, None, str(exc)
    try:
        cur = conn.cursor()
        quote = '`' if db['engine'] == 'mysql' else '"'
        cur.execute(f'SELECT * FROM {quote}{table}{quote} LIMIT %s', (limit,))
        columns = [c[0] for c in cur.description]
        rows = cur.fetchall()
        return columns, rows, ''
    except Exception as exc:
        return None, None, str(exc)
    finally:
        conn.close()


def run_query(db, sql, allow_write=False):
    if not allow_write and _WRITE_RE.match(sql or ''):
        return None, None, 'Esta conexión es de solo lectura. Activa "permitir escritura" para correr esto.'
    try:
        conn = _connect(db)
    except Exception as exc:
        return None, None, str(exc)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        if cur.description:
            columns = [c[0] for c in cur.description]
            rows = cur.fetchmany(500)
        else:
            columns, rows = [], []
            conn.commit()
        return columns, rows, ''
    except Exception as exc:
        conn.rollback()
        return None, None, str(exc)
    finally:
        conn.close()
