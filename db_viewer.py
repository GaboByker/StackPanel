"""Visor de bases de datos por proyecto (MySQL/MariaDB y Postgres). Solo lectura salvo que se permita escritura."""
import re

SAFE_IDENT_RE = re.compile(r'^[A-Za-z0-9_]+$')
_WRITE_RE = re.compile(r'^(insert|update|delete|drop|alter|create|truncate|grant|revoke|replace|merge)\b', re.IGNORECASE)
# Comentarios y espacios iniciales que podrían ocultar una escritura ("/*x*/DELETE …").
_LEADING_NOISE_RE = re.compile(r'^(\s+|/\*.*?\*/|--[^\n]*\n?|#[^\n]*\n?)', re.DOTALL)


def _is_write_query(sql):
    """True si la consulta modifica datos. Ante la duda (varias sentencias) se considera escritura."""
    text = sql or ''
    prev = None
    while text != prev:
        prev = text
        text = _LEADING_NOISE_RE.sub('', text, count=1)
    if _WRITE_RE.match(text):
        return True
    # psycopg2 ejecuta todas las sentencias encadenadas; el ';' final no cuenta.
    return len(_split_statements(text)) > 1


def _split_statements(text):
    """Separa por ';' respetando comillas y comentarios."""
    stmts, buf = [], []
    i, n = 0, len(text)
    quote = None
    while i < n:
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
        elif ch == ';':
            stmt = ''.join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = ''.join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


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
    if not allow_write and _is_write_query(sql):
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
