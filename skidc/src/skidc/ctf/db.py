"""Instance-scoped SQLite storage; incompatible files are never migrated implicitly."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

APPLICATION_ID = 0x53435446  # SCTF; legacy databases have application_id=0.
SCHEMA_VERSION = 4

from .schema import SCHEMA, TABLES



class DatabaseCompatibilityError(RuntimeError):
    """The selected file is not a compatible CTF database."""


class CtfDatabase:
    def __init__(self, path: Path):
        if str(path) == ":memory:":
            raise ValueError("CTF requires an explicit on-disk database path")
        self.path = Path(path).expanduser().resolve()

    def _connect(self, *, create: bool = False, read_only: bool = False) -> sqlite3.Connection:
        mode = "ro" if read_only else ("rwc" if create else "rw")
        conn = sqlite3.connect(f"{self.path.as_uri()}?mode={mode}", uri=True, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _empty(conn: sqlite3.Connection) -> bool:
        return (
            not conn.execute("SELECT name FROM sqlite_master").fetchall()
            and conn.execute("PRAGMA application_id").fetchone()[0] == 0
            and conn.execute("PRAGMA user_version").fetchone()[0] == 0
        )

    @staticmethod
    def _validate(conn: sqlite3.Connection) -> None:
        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if app_id != APPLICATION_ID or version != SCHEMA_VERSION or tables != TABLES:
            raise DatabaseCompatibilityError("Expected a CTF database with schema version 4; use explicit copy-upgrade for older CTF files")
        rows = conn.execute("SELECT engine, schema_version FROM engine_metadata").fetchall()
        if len(rows) != 1 or tuple(rows[0]) != ("ctf", SCHEMA_VERSION):
            raise DatabaseCompatibilityError("CTF database identity does not match its schema")

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            # Even closing an otherwise unused writable connection can checkpoint
            # another engine's WAL. Inspect existing files read-only first.
            probe = self._connect(read_only=True)
            try:
                probe.execute("BEGIN")
                if not self._empty(probe):
                    self._validate(probe)
            finally:
                probe.close()
        conn = self._connect(create=True)
        try:
            conn.execute("BEGIN IMMEDIATE")
            if self._empty(conn):
                for statement in SCHEMA:
                    conn.execute(statement)
                conn.execute("INSERT INTO engine_metadata VALUES(1, 'ctf', ?)", (SCHEMA_VERSION,))
                conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
                conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._validate(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            if not write:
                conn.execute("PRAGMA query_only=ON")
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            self._validate(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
