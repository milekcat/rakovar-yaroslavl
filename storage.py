"""Small, bounded DB-API bridge for the existing Rakovar queries.

SQLite remains the local preview backend. DATABASE_URL selects PostgreSQL.
The bridge supports only the SQL shapes used here, not arbitrary SQLite SQL.
Every connection context is one transaction; the coarse transaction lock keeps
legacy read/modify/write flows correct across web and bot processes.
"""
from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator
from urllib.parse import urlsplit

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
LOCK_ID = 7244167620261109
IDENTITY_TABLES = frozenset({
    "spins", "contest_entries", "contest_winners", "content_posts", "events",
    "ticket_ledger", "audit_log",
})
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class StorageConfigurationError(RuntimeError):
    pass


class Row(Mapping):
    """sqlite3.Row-style key/index access, with dict(row) support."""
    def __init__(self, names, values):
        self._names = tuple(names)
        self._values = tuple(values)
        self._indexes = {name: index for index, name in enumerate(names)}

    def __getitem__(self, key):
        return self._values[key if isinstance(key, (int, slice)) else self._indexes[key]]

    def __iter__(self):
        return iter(self._names)

    def __len__(self):
        return len(self._names)


class Result:
    def __init__(self, cursor=None, *, rows=None, rowcount=0, lastrowid=None):
        self._cursor = cursor
        self._rows = iter(rows or []) if cursor is None else None
        self.rowcount = cursor.rowcount if cursor is not None else rowcount
        self.lastrowid = lastrowid
        self._names = [column.name for column in cursor.description] if cursor is not None and cursor.description else []

    def fetchone(self):
        if self._cursor is None:
            return next(self._rows, None)
        if not self._names:
            return None
        value = self._cursor.fetchone()
        return Row(self._names, value) if value is not None else None

    def fetchall(self):
        return list(self)

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                return
            yield row


def _tokens(sql: str):
    """Yield quoted strings/comments and SQL separately; no parameter rewriting inside literals."""
    token = re.compile(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*(?:\n|$)|/\*.*?\*/)", re.S)
    return token.split(sql)


def _qmarks(sql: str) -> str:
    parts = _tokens(sql)
    for index in range(0, len(parts), 2):
        parts[index] = parts[index].replace("?", "%s")
    # Psycopg's parameter parser also interprets % inside string literals.
    return "".join(part.replace("%", "%%") if index % 2 else part for index, part in enumerate(parts))


def _statements(script: str):
    buffer = ""
    # sqlite3.complete_statement understands semicolons inside strings/comments.
    for part in script:
        buffer += part
        if part == ";" and sqlite3.complete_statement(buffer):
            yield buffer.strip()
            buffer = ""
    if buffer.strip():
        yield buffer.strip()


class SQLiteConnection:
    dialect = "sqlite"

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, parameters=()):
        if sql.strip().upper() == "BEGIN IMMEDIATE" and self.raw.in_transaction:
            return Result()
        return self.raw.execute(sql, parameters)

    def executemany(self, sql, parameters):
        return self.raw.executemany(sql, parameters)

    def executescript(self, script):
        # Native executescript implicitly commits; avoid breaking migration atomicity.
        for statement in _statements(script):
            self.raw.execute(statement)

    def __getattr__(self, name):
        return getattr(self.raw, name)


class PostgresConnection:
    dialect = "postgresql"

    def __init__(self, raw, driver):
        self.raw = raw
        self.driver = driver
        self._lastrowid = None

    def execute(self, sql, parameters=()):
        query = sql.strip().rstrip(";")
        if query.upper() in {"BEGIN IMMEDIATE", "BEGIN"}:
            return Result()
        if query.lower() == "select last_insert_rowid()":
            return Result(rows=[Row(["last_insert_rowid()"], [self._lastrowid])])
        pragma = re.fullmatch(r"PRAGMA\s+table_info\((\w+)\)", query, re.I)
        if pragma:
            return self.execute("""SELECT ordinal_position - 1 AS cid, column_name AS name,
                data_type AS type FROM information_schema.columns
                WHERE table_schema=current_schema() AND table_name=? ORDER BY ordinal_position""", (pragma[1],))
        if query.upper().startswith("PRAGMA"):
            raise sqlite3.NotSupportedError("This PRAGMA is not supported by PostgreSQL")

        ignore = bool(re.match(r"INSERT\s+OR\s+IGNORE\s+INTO\b", query, re.I))
        replace = bool(re.match(r"INSERT\s+OR\s+REPLACE\s+INTO\b", query, re.I))
        if ignore:
            query = re.sub(r"^INSERT\s+OR\s+IGNORE", "INSERT", query, count=1, flags=re.I) + " ON CONFLICT DO NOTHING"
        if replace:
            if not re.match(r"INSERT\s+OR\s+REPLACE\s+INTO\s+site_settings\b", query, re.I):
                raise sqlite3.NotSupportedError("OR REPLACE is supported only for site_settings")
            query = re.sub(r"^INSERT\s+OR\s+REPLACE", "INSERT", query, count=1, flags=re.I)
            query += " ON CONFLICT(setting_key) DO UPDATE SET setting_value=EXCLUDED.setting_value,updated_at=EXCLUDED.updated_at"
        query = re.sub(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", query, flags=re.I)
        inserted = re.match(r"INSERT\s+INTO\s+(\w+)\b", query, re.I)
        implicit_returning = bool(inserted and inserted[1] in IDENTITY_TABLES and not re.search(r"\bRETURNING\b", query, re.I))
        if implicit_returning:
            query += " RETURNING id"
        # LIMIT/OFFSET and numeric/JSON expressions are otherwise native PostgreSQL SQL.
        # Do not silently guess at unsupported SQLite-specific functions.
        if parameters:
            query = _qmarks(query)
        try:
            # Per-statement savepoint preserves the existing application's ability
            # to catch IntegrityError and continue its surrounding transaction.
            with self.raw.transaction():
                cursor = self.raw.execute(query, parameters if parameters else None)
                result = Result(cursor)
                if implicit_returning:
                    row = cursor.fetchone()
                    self._lastrowid = row[0] if row else None
                    result.lastrowid = self._lastrowid
                    result._names = []
                return result
        except self.driver.IntegrityError:
            raise sqlite3.IntegrityError("database constraint violation") from None
        except self.driver.Error as error:
            raise sqlite3.DatabaseError(f"PostgreSQL statement failed (SQLSTATE={error.sqlstate or 'unknown'})") from None

    def executemany(self, sql, parameters):
        count = 0
        for values in parameters:
            count += max(0, self.execute(sql, values).rowcount)
        return Result(rowcount=count, lastrowid=self._lastrowid)

    def executescript(self, script):
        for statement in _statements(script):
            self.execute(statement)

    def __getattr__(self, name):
        return getattr(self.raw, name)


@contextmanager
def connect_database(sqlite_path: str | Path, *, database_url: str | None = None):
    """Commit on normal exit and roll back on exceptions, with one connection per unit of work.

    An empty explicit database_url forces SQLite for tests. An omitted value
    reads DATABASE_URL. No fallback to SQLite occurs after a PostgreSQL failure.
    """
    url = os.environ.get("DATABASE_URL", "").strip() if database_url is None else database_url.strip()
    if not url:
        path = Path(sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(str(path), timeout=15)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys=ON")
        raw.execute("PRAGMA busy_timeout=15000")
        connection = SQLiteConnection(raw)
        try:
            raw.execute("BEGIN IMMEDIATE")
            yield connection
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()
        return
    if urlsplit(url).scheme not in {"postgres", "postgresql"}:
        raise StorageConfigurationError("DATABASE_URL must use postgres:// or postgresql://")
    try:
        import psycopg
    except ImportError:
        raise StorageConfigurationError("PostgreSQL requires the pinned psycopg dependency") from None
    raw = None
    try:
        raw = psycopg.connect(url, connect_timeout=10)
        with raw.transaction():
            raw.execute("SET LOCAL statement_timeout = '15s'")
            raw.execute("SET LOCAL lock_timeout = '10s'")
            # Transitional lock intentionally serializes ALL legacy transactions.
            # Replace with explicit row locks only after each workflow is isolated.
            raw.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
            yield PostgresConnection(raw, psycopg)
    except psycopg.Error as error:
        raise sqlite3.DatabaseError(f"PostgreSQL unavailable (SQLSTATE={error.sqlstate or 'connection'})") from None
    finally:
        if raw is not None:
            raw.close()


def migrate(connection) -> list[str]:
    """Apply checksummed, additive migrations in the caller's transaction."""
    connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL
    )""")
    applied = {row["version"]: row["checksum"] for row in connection.execute("SELECT version,checksum FROM schema_migrations")}
    files = sorted([*MIGRATIONS.glob("*.sql"), *MIGRATIONS.glob("*.json")])
    names = {path.stem for path in files}
    if set(applied) - names:
        raise StorageConfigurationError("Database contains migrations newer than this application")
    completed = []
    for path in files:
        data = path.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        if path.stem in applied:
            if applied[path.stem] != checksum:
                raise StorageConfigurationError(f"Migration checksum mismatch: {path.name}")
            continue
        if path.suffix == ".sql":
            connection.executescript(data.decode("utf-8"))
        else:
            for table, column, declaration in json.loads(data)["add_columns"]:
                if not _IDENTIFIER.fullmatch(table) or not _IDENTIFIER.fullmatch(column):
                    raise StorageConfigurationError("Invalid migration identifier")
                existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        connection.execute("INSERT INTO schema_migrations(version,checksum,applied_at) VALUES(?,?,?)",
                           (path.stem, checksum, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
        completed.append(path.stem)
    return completed


def top_products(connection, cutoff):
    """The one JSON analytics query has explicit backend-specific SQL."""
    if connection.dialect == "postgresql":
        sql = """SELECT p.title,COUNT(*) qty FROM orders o
            CROSS JOIN LATERAL jsonb_array_elements(o.items_json::jsonb) j(value)
            JOIN products p ON p.id=j.value->>'id' WHERE o.created_at>=?
            GROUP BY p.id,p.title ORDER BY qty DESC LIMIT 5"""
    else:
        sql = """SELECT p.title,COUNT(*) qty FROM orders o,json_each(o.items_json) j
            JOIN products p ON p.id=json_extract(j.value,'$.id') WHERE o.created_at>=?
            GROUP BY p.id ORDER BY qty DESC LIMIT 5"""
    return connection.execute(sql, (cutoff,)).fetchall()
