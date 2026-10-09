"""Small SQLite/PostgreSQL compatibility layer for simulation persistence."""
from pathlib import Path
import sqlite3


class StorageIntegrityError(Exception):
    """Raised when a database uniqueness or foreign-key constraint fails."""


class Storage:
    def __init__(self, target):
        value = str(target)
        self.postgres = value.startswith(("postgres://", "postgresql://"))
        if self.postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("PostgreSQL persistence requires psycopg.") from exc
            self._integrity_error = psycopg.IntegrityError
            self.connection = psycopg.connect(value, row_factory=dict_row)
        else:
            if value.startswith("sqlite:///"):
                value = value[10:]
            if value != ":memory:":
                path = Path(value).resolve()
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                value = str(path)
            self._integrity_error = sqlite3.IntegrityError
            self.connection = sqlite3.connect(value)
            self.connection.row_factory = sqlite3.Row
        self.initialize()
        if not self.postgres and value != ":memory:":
            Path(value).chmod(0o600)

    def _sql(self, sql):
        return sql.replace("?", "%s") if self.postgres else sql

    def execute(self, sql, params=()):
        try:
            return self.connection.execute(self._sql(sql), params)
        except self._integrity_error as exc:
            raise StorageIntegrityError() from exc

    def initialize(self):
        event_key = "BIGSERIAL PRIMARY KEY" if self.postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
        statements = [
            """CREATE TABLE IF NOT EXISTS sessions(
                 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, status TEXT NOT NULL,
                 case_id TEXT NOT NULL, snapshot TEXT NOT NULL, source_hash TEXT NOT NULL,
                 feedback_requested INTEGER NOT NULL DEFAULT 0)""",
            "CREATE UNIQUE INDEX IF NOT EXISTS one_active ON sessions(owner_id) WHERE status='active'",
            f"""CREATE TABLE IF NOT EXISTS events(
                 seq {event_key}, session_id TEXT NOT NULL, at TEXT NOT NULL,
                 kind TEXT NOT NULL, payload TEXT NOT NULL,
                 FOREIGN KEY(session_id) REFERENCES sessions(id))""",
            """CREATE TABLE IF NOT EXISTS evidence(
                 ref TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL,
                 FOREIGN KEY(session_id) REFERENCES sessions(id))""",
            """CREATE TABLE IF NOT EXISTS disclosures(
                 session_id TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL,
                 transport TEXT NOT NULL DEFAULT 'returned', PRIMARY KEY(session_id, filename),
                 FOREIGN KEY(session_id) REFERENCES sessions(id))""",
        ]
        if not self.postgres:
            self.connection.execute("PRAGMA foreign_keys=ON")
        for statement in statements:
            self.connection.execute(statement)
        self.connection.commit()

    def upsert_disclosure(self, session_id, filename, sha256):
        self.execute(
            """INSERT INTO disclosures(session_id, filename, sha256) VALUES(?,?,?)
               ON CONFLICT(session_id, filename) DO UPDATE SET sha256=excluded.sha256,
               transport='returned'""",
            (session_id, filename, sha256),
        )

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False
