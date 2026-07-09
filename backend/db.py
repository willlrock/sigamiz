import os
import re
import sqlite3

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SQLITE_DB_PATH = os.path.join(BASE_DIR, "backend", "database.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "backend", "schema.sql")
DATABASE_URL = os.getenv("DATABASE_URL")


def is_postgres():
    return bool(DATABASE_URL and DATABASE_URL.startswith(("postgres://", "postgresql://")))


def _postgres_module():
    try:
        import psycopg2
        import psycopg2.extras
    except ModuleNotFoundError as exc:
        raise RuntimeError("DATABASE_URL is set, but psycopg2-binary is not installed") from exc
    return psycopg2, psycopg2.extras


def _translate_postgres_sql(sql):
    sql = sql.strip()
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    sql = sql.replace("BOOLEAN", "INTEGER")
    sql = sql.replace("DATETIME", "TIMESTAMP")
    sql = sql.replace("REAL", "DOUBLE PRECISION")
    sql = re.sub(r"datetime\('now',\s*'\+7 days'\)", "(CURRENT_TIMESTAMP + INTERVAL '7 days')", sql, flags=re.I)
    sql = re.sub(r"datetime\('now',\s*'\+10 minutes'\)", "(CURRENT_TIMESTAMP + INTERVAL '10 minutes')", sql, flags=re.I)
    sql = re.sub(r"datetime\('now'\)", "CURRENT_TIMESTAMP", sql, flags=re.I)

    if re.match(r"^INSERT\s+OR\s+REPLACE\s+INTO\s+banned_users", sql, flags=re.I):
        sql = re.sub(r"^INSERT\s+OR\s+REPLACE\s+", "INSERT ", sql, flags=re.I)
        sql += " ON CONFLICT (telegram_user_id) DO UPDATE SET reason = EXCLUDED.reason, banned_at = CURRENT_TIMESTAMP"
    elif re.match(r"^INSERT\s+OR\s+IGNORE\s+", sql, flags=re.I):
        sql = re.sub(r"^INSERT\s+OR\s+IGNORE\s+", "INSERT ", sql, flags=re.I)
        if "ON CONFLICT" not in sql.upper():
            sql += " ON CONFLICT DO NOTHING"

    return sql.replace("?", "%s")


def _postgres_schema(sql):
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    sql = sql.replace("BOOLEAN", "INTEGER")
    sql = sql.replace("DATETIME", "TIMESTAMP")
    sql = sql.replace("REAL", "DOUBLE PRECISION")
    return sql


def _split_sql_script(script):
    statements = []
    current = []
    in_single = False
    in_double = False
    for char in script:
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        if char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


class PostgresCursor:
    is_postgres = True

    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = None

    def execute(self, sql, params=None):
        if re.match(r"^PRAGMA\s+table_info\(([^)]+)\)", sql.strip(), flags=re.I):
            table_name = re.match(r"^PRAGMA\s+table_info\(([^)]+)\)", sql.strip(), flags=re.I).group(1).strip("\"'")
            self.cursor.execute(
                """
                SELECT ordinal_position - 1 AS cid, column_name AS name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name,),
            )
            rows = self.cursor.fetchall()
            self._pragma_rows = [(row["cid"], row["name"]) for row in rows]
            return self

        self._pragma_rows = None
        sql = _translate_postgres_sql(sql)
        if params is None:
            self.cursor.execute(sql)
        else:
            self.cursor.execute(sql, params)
        return self

    def fetchone(self):
        if getattr(self, "_pragma_rows", None) is not None:
            return self._pragma_rows[0] if self._pragma_rows else None
        return self.cursor.fetchone()

    def fetchall(self):
        if getattr(self, "_pragma_rows", None) is not None:
            return self._pragma_rows
        return self.cursor.fetchall()

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def __iter__(self):
        return iter(self.fetchall())


class PostgresConnection:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return PostgresCursor(self.conn.cursor())

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()


def get_db():
    if is_postgres():
        psycopg2, extras = _postgres_module()
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=extras.DictCursor)
        return PostgresConnection(conn)
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def execute_schema(cursor):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()
    if is_postgres():
        for statement in _split_sql_script(_postgres_schema(schema)):
            cursor.execute(statement)
    else:
        cursor.executescript(schema)
