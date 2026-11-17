"""Offline schema-1/2/3 copy-upgrade; never replace or write to the source."""
from pathlib import Path
import sqlite3

from .db import APPLICATION_ID, CtfDatabase, DatabaseCompatibilityError
from .schema import TABLES_V1, TABLES_V2, TABLES_V3


def upgrade_copy(source: Path, destination: Path) -> None:
    source, destination = Path(source).resolve(), Path(destination).resolve()
    src = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    owned = False
    try:
        src.execute("BEGIN")
        tables = {row[0] for row in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = src.execute("PRAGMA user_version").fetchone()[0]
        expected_tables = {1: TABLES_V1, 2: TABLES_V2, 3: TABLES_V3}.get(version)
        if (src.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                or expected_tables is None or tables != expected_tables):
            raise DatabaseCompatibilityError("copy-upgrade requires a schema-1, schema-2 or schema-3 CTF source")
        if src.execute("SELECT engine,schema_version FROM engine_metadata").fetchall() != [("ctf", version)]:
            raise DatabaseCompatibilityError("CTF source metadata mismatch")
        if version >= 2 and (
            src.execute("SELECT 1 FROM runs WHERE status!='stopped' OR cleanup_state!='confirmed' LIMIT 1").fetchone()
            or src.execute("SELECT 1 FROM task_attempts WHERE status='leased' LIMIT 1").fetchone()
            or src.execute("SELECT 1 FROM runtime_operations WHERE status!='confirmed' LIMIT 1").fetchone()
            or src.execute("SELECT 1 FROM projects WHERE status='active' LIMIT 1").fetchone()
        ):
            raise DatabaseCompatibilityError("Stop all source runs and confirm cleanup before copy-upgrade")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb"):
            pass
        owned = True
        db = CtfDatabase(destination)
        db.initialize()
        with db.connection(write=True) as dst:
            dst.execute("PRAGMA defer_foreign_keys=ON")
            for table in sorted(expected_tables - {"engine_metadata"}):
                cursor = src.execute(f'SELECT * FROM "{table}"')
                source_columns = [col[0] for col in cursor.description]
                expected_columns = [col[0] for col in dst.execute(f'SELECT * FROM "{table}" LIMIT 0').description]
                if source_columns != expected_columns:
                    raise DatabaseCompatibilityError(f"Unexpected schema-{version} columns in {table}")
                columns = ",".join(f'"{name}"' for name in expected_columns)
                placeholders = ",".join("?" for _ in cursor.description)
                dst.executemany(f'INSERT INTO "{table}"({columns}) VALUES({placeholders})', cursor)
            if dst.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise DatabaseCompatibilityError("Source contains invalid cross-project references")
            if dst.execute("""SELECT 1 FROM projects p LEFT JOIN board_state b
                ON b.project_id=p.id WHERE b.project_id IS NULL LIMIT 1""").fetchone():
                raise DatabaseCompatibilityError("Source project is missing its blackboard revision")
    except Exception:
        if owned:
            destination.unlink(missing_ok=True)
        raise
    finally:
        src.close()
