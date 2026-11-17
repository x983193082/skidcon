from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import UUID

import pytest
from pydantic import ValidationError


def make_store(path):
    from skidc.ctf.db import CtfDatabase
    from skidc.ctf.store import BoardStore

    database = CtfDatabase(path)
    database.initialize()
    return database, BoardStore(database)


def request(**kwargs):
    from skidc.ctf.models import CreateProject

    return CreateProject(title="CTF", origin="http://challenge.local", goal="Find the flag", **kwargs)


@pytest.mark.parametrize("extra", [
    {"mode": "real_website"}, {"mode": None}, {"coverage": []},
    {"recon_profile": {}}, {"status": "completed"}, {"bootstrap_enabled": "false"},
])
def test_ctf_request_rejects_foreign_fields(extra):
    with pytest.raises(ValidationError):
        request(**extra)


def test_project_is_an_independent_draft_blackboard(tmp_path):
    database, store = make_store(tmp_path / "ctf.db")
    board = store.create_project(request(bootstrap_enabled=False))
    assert str(UUID(board.project.id)) == board.project.id
    assert board.project.mode == "ctf"
    assert board.project.status == "draft"
    assert board.project.bootstrap_enabled is False
    assert board.project.current_run_id is None
    assert board.project.goal_version == 1
    assert board.revision == 1
    assert {fact.id: fact.description for fact in board.facts} == {
        "origin": "http://challenge.local", "goal": "Find the flag",
    }
    assert board.intents == board.hints == []
    assert store.get_board(board.project.id) == board
    with database.connection() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"coverage_items", "hypotheses", "surface_inventory", "settings"} & tables
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_instances_do_not_retarget_each_others_database_and_survive_restart(tmp_path):
    first_db, first = make_store(tmp_path / "first.db")
    first_board = first.create_project(request())
    _, second = make_store(tmp_path / "second.db")
    second_board = second.create_project(request())
    assert first_board.project.id != second_board.project.id
    assert [p.id for p in first.list_projects()] == [first_board.project.id]
    assert [p.id for p in second.list_projects()] == [second_board.project.id]
    _, reopened = make_store(first_db.path)
    assert reopened.get_board(first_board.project.id) == first_board


@pytest.mark.parametrize("kind", ["legacy", "unknown", "future", "wrong_engine", "missing_table"])
def test_incompatible_database_is_rejected_without_changes(tmp_path, kind):
    from skidc.ctf.db import CtfDatabase, DatabaseCompatibilityError

    path = tmp_path / "existing.db"
    if kind in {"legacy", "unknown"}:
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TABLE projects(id TEXT)" if kind == "legacy" else "CREATE TABLE unrelated(value TEXT)")
    else:
        database, _ = make_store(path)
        with sqlite3.connect(path) as conn:
            if kind == "future":
                conn.execute("PRAGMA user_version = 999")
            elif kind == "wrong_engine":
                conn.execute("UPDATE engine_metadata SET engine = 'web'")
            else:
                conn.execute("DROP TABLE hints")
    before = path.read_bytes()
    with pytest.raises(DatabaseCompatibilityError):
        CtfDatabase(path).initialize()
    assert path.read_bytes() == before


def test_blank_db_with_nonzero_version_is_not_adopted(tmp_path):
    from skidc.ctf.db import CtfDatabase, DatabaseCompatibilityError

    path = tmp_path / "reserved.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version = 9")
    before = path.read_bytes()
    with pytest.raises(DatabaseCompatibilityError):
        CtfDatabase(path).initialize()
    assert path.read_bytes() == before


def test_rejected_legacy_database_does_not_checkpoint_its_wal(tmp_path):
    from skidc.ctf.db import CtfDatabase, DatabaseCompatibilityError

    path = tmp_path / "legacy.db"
    # A terminated server can leave committed transactions only in the WAL.
    # Opening it writable and closing the last connection checkpoints even if
    # our code never explicitly modifies a table.
    result = subprocess.run([
        sys.executable, "-c",
        "import os, sqlite3, sys; "
        "conn = sqlite3.connect(sys.argv[1]); "
        "conn.execute('PRAGMA journal_mode=WAL'); "
        "conn.execute('CREATE TABLE projects(id TEXT)'); "
        "conn.execute(\"INSERT INTO projects VALUES('keep-me')\"); "
        "conn.commit(); os._exit(0)",
        str(path),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    wal = Path(str(path) + "-wal")
    before, wal_before = path.read_bytes(), wal.read_bytes()
    with pytest.raises(DatabaseCompatibilityError):
        CtfDatabase(path).initialize()
    assert path.read_bytes() == before
    assert wal.read_bytes() == wal_before


def test_composite_foreign_keys_reject_other_projects_fact(tmp_path):
    database, store = make_store(tmp_path / "ctf.db")
    a = store.create_project(request()).project.id
    b = store.create_project(request()).project.id
    with database.connection(write=True) as conn:
        conn.execute("INSERT INTO facts(project_id,id,description,created_at) VALUES(?, 'only-a', 'private', 'now')", (a,))
        conn.execute("INSERT INTO intents(project_id,id,description,created_at) VALUES(?, 'i1', 'explore', 'now')", (b,))
    with pytest.raises(sqlite3.IntegrityError):
        with database.connection(write=True) as conn:
            conn.execute("INSERT INTO intent_sources(project_id,intent_id,fact_id) VALUES(?, 'i1', 'only-a')", (b,))
    assert store.get_board(b).intents[0].from_ == []


def test_project_creation_rolls_back_when_reserved_fact_fails(tmp_path):
    database, store = make_store(tmp_path / "ctf.db")
    with database.connection(write=True) as conn:
        conn.execute("""CREATE TRIGGER reject_goal BEFORE INSERT ON facts WHEN NEW.id='goal'
                        BEGIN SELECT RAISE(ABORT, 'injected storage failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected storage failure"):
        store.create_project(request())
    assert store.list_projects() == []
    with database.connection() as conn:
        assert conn.execute("SELECT count(*) FROM facts").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM board_state").fetchone()[0] == 0


def test_parallel_hints_increment_revision_without_lost_writes(tmp_path):
    from skidc.ctf.models import CreateHint

    database, store = make_store(tmp_path / "ctf.db")
    pid = store.create_project(request()).project.id
    with ThreadPoolExecutor(max_workers=4) as pool:
        hints = list(pool.map(lambda n: store.add_hint(pid, CreateHint(content=f"hint {n}", creator="operator")), range(12)))
    board = store.get_board(pid)
    assert len({hint.id for hint in hints}) == len(board.hints) == 12
    assert board.revision == 13
    assert {hint.content for hint in board.hints} == {f"hint {n}" for n in range(12)}
    assert all(hint.creator == "operator" for hint in board.hints)


def test_read_snapshot_is_consistent_across_concurrent_commit(tmp_path):
    from skidc.ctf.models import CreateHint

    database, store = make_store(tmp_path / "ctf.db")
    pid = store.create_project(request()).project.id
    # WAL allows the writer to commit while the reader keeps its original snapshot.
    with sqlite3.connect(database.path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    with database.connection() as conn:
        assert conn.execute("SELECT semantic_revision FROM board_state").fetchone()[0] == 1
        store.add_hint(pid, CreateHint(content="new hint"))
        assert conn.execute("SELECT count(*) FROM hints").fetchone()[0] == 0
    assert store.get_board(pid).revision == 2


def test_missing_project_writes_do_not_create_orphan_hints(tmp_path):
    from skidc.ctf.models import CreateHint
    from skidc.ctf.store import ProjectNotFound

    database, store = make_store(tmp_path / "ctf.db")
    with pytest.raises(ProjectNotFound):
        store.add_hint("missing", CreateHint(content="clue"))
    with database.connection() as conn:
        assert conn.execute("SELECT count(*) FROM hints").fetchone()[0] == 0


def test_mode_is_immutable_even_at_storage_boundary(tmp_path):
    database, store = make_store(tmp_path / "ctf.db")
    pid = store.create_project(request()).project.id
    with pytest.raises(sqlite3.IntegrityError):
        with database.connection(write=True) as conn:
            conn.execute("UPDATE projects SET mode='real_website' WHERE id=?", (pid,))
    assert store.get_board(pid).project.mode == "ctf"
