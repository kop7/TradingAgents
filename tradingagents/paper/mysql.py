"""MySQL storage adapter for the paper repository's parameterized query interface."""

from __future__ import annotations

import hashlib
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime

from tradingagents.paper.database import SCHEMA_VERSION


def mysql_query(sql: str) -> str:
    """Translate the repository's limited SQLite upsert syntax; never interpolate values."""
    sql = re.sub(
        r"ON CONFLICT\((\w+)(?:,\s*\w+)*\) DO NOTHING",
        r"ON DUPLICATE KEY UPDATE \1 = \1", sql,
    )
    sql = re.sub(r"ON CONFLICT\([\w, ]+\)\s*DO UPDATE SET", "ON DUPLICATE KEY UPDATE", sql)
    sql = re.sub(r"excluded\.(\w+)", r"VALUES(\1)", sql)
    # Queries are internal constants; the repository uses ? only for bind parameters.
    return sql.replace("%", "%%").replace("?", "%s")


class Row(dict):
    def __iter__(self):
        # sqlite3.Row iterates values, while dict(row) uses its mapping keys.
        return iter(self.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Result:
    def __init__(self, cursor):
        self.rowcount = cursor.rowcount
        self.description = getattr(cursor, "description", None)
        self.lastrowid = getattr(cursor, "lastrowid", None)
        self.rows = (
            iter(Row(row) for row in cursor.fetchall())
            if self.description else iter(())
        )

    def fetchone(self):
        return next(self.rows, None)

    def fetchall(self):
        return list(self.rows)

    def __iter__(self):
        return self.rows


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, parameters=()):
        with self.raw.cursor() as cursor:
            cursor.execute(mysql_query(sql), parameters)
            return Result(cursor)

    def executemany(self, sql, parameters):
        with self.raw.cursor() as cursor:
            cursor.executemany(mysql_query(sql), parameters)
            return Result(cursor)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                self.raw.commit()
            else:
                self.raw.rollback()
        finally:
            self.raw.close()


class MySQLDatabase:
    def __init__(self, *, host, port, database, user, password):
        self.settings = {
            "host": host, "port": port, "database": database, "user": user, "password": password,
        }
        digest = hashlib.sha256(database.encode()).hexdigest()[:32]
        self.lock_name = f"tradingagents:paper:{digest}"

    @classmethod
    def from_env(cls):
        missing = [key for key in ("DB_HOST", "DB_DATABASE", "DB_USERNAME") if not os.getenv(key)]
        if missing:
            raise ValueError("Missing MySQL settings: " + ", ".join(missing))
        try:
            port = int(os.getenv("DB_PORT", "3306"))
        except ValueError as exc:
            raise ValueError("DB_PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("DB_PORT must be between 1 and 65535")
        return cls(
            host=os.environ["DB_HOST"], port=port, database=os.environ["DB_DATABASE"],
            user=os.environ["DB_USERNAME"], password=os.getenv("DB_PASSWORD", ""),
        )

    def connect(self):
        import pymysql

        return Connection(pymysql.connect(
            **self.settings, charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
            autocommit=True, connect_timeout=10, read_timeout=30, write_timeout=30,
        ))

    def initialize(self):
        """Check migrations on normal use; DDL is only run by the migrate command."""
        with self.connect() as connection:
            exists = connection.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = 'schema_migrations'"
            ).fetchone()[0]
            version = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()[0] if exists else 0
        if version != SCHEMA_VERSION:
            raise RuntimeError(
                f"MySQL paper schema version {version}; expected {SCHEMA_VERSION}. "
                "Run: tradingagents db migrate"
            )
        return self

    @contextmanager
    def transaction(self):
        # Match SQLite BEGIN IMMEDIATE serialization, including absent-row checks.
        # The session lock survives MySQL's implicit DDL commits during migrations.
        with self.connect() as connection:
            if connection.execute("SELECT GET_LOCK(?, 10)", (self.lock_name,)).fetchone()[0] != 1:
                raise RuntimeError("Timed out waiting for the paper database lock")
            try:
                connection.raw.begin()
                yield connection
                connection.raw.commit()
            except Exception:
                connection.raw.rollback()
                raise
            finally:
                connection.execute("SELECT RELEASE_LOCK(?)", (self.lock_name,))

    def migrate(self):
        from tradingagents.paper.mysql_schema import MIGRATIONS, TRIGGERS

        with self.transaction() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version BIGINT PRIMARY KEY, name VARCHAR(255) NOT NULL,
                applied_at VARCHAR(40) NOT NULL
            ) ENGINE=InnoDB""")
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            if applied and max(applied) > SCHEMA_VERSION:
                raise RuntimeError("MySQL schema is newer than this application")
            for version, name, statements in MIGRATIONS:
                if version in applied:
                    continue
                for statement in statements:
                    connection.execute(statement)
                for trigger, statement in TRIGGERS.items():
                    exists = connection.execute(
                        "SELECT COUNT(*) FROM information_schema.triggers "
                        "WHERE trigger_schema = DATABASE() AND trigger_name = ?", (trigger,),
                    ).fetchone()[0]
                    if not exists:
                        connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (version, name, datetime.now(UTC).isoformat()),
                )
