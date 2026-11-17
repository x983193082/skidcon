from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from skidc.ctf.db import CtfDatabase, DatabaseCompatibilityError
from skidc.ctf.models import CreateHint, CreateProject
from skidc.ctf.store import BoardStore


@pytest.fixture
def runtime(tmp_path):
    from skidc.ctf.runtime import RuntimeStore

    db = CtfDatabase(tmp_path / "ctf.db")
    db.initialize()
    now = [1_000.0]
    board = BoardStore(db)
    pid = board.create_project(CreateProject(title="ctf", origin="target", goal="solve", bootstrap_enabled=False)).project.id
    return db, board, RuntimeStore(db, clock=lambda: now[0]), pid, now


def start(rt, pid, key="start-1", target="target-1"):
    from skidc.ctf.runtime_models import StartRun
    return rt.start(pid, StartRun(idempotency_key=key, target_instance_id=target))


def claim(rt, pid, run, kind="reason", intent_id=None, worker="worker-instance-1"):
    from skidc.ctf.runtime_models import ClaimTask
    return rt.claim(pid, run["id"], ClaimTask(kind=kind, intent_id=intent_id, worker_instance_id=worker))


def result_body(grant, key=None, **payload):
    from skidc.ctf.runtime_models import TaskResult
    return TaskResult(worker_instance_id=grant["worker_instance_id"], lease_token=grant["lease_token"], idempotency_key=key or f"result-{grant['id']}", **payload)


def plan(rt, pid, run):
    grant = claim(rt, pid, run)
    result = rt.submit(pid, run["id"], grant["id"], result_body(grant, intents=[{"from": ["origin"], "description": "Inspect"}]))
    return result["intent_ids"][0]


def test_runs_are_idempotent_and_versions_are_bound(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    db, board, rt, pid, _ = runtime
    run = start(rt, pid)
    assert start(rt, pid) == run
    assert run["generation"] == 1 and run["schema_version"] == 4
    assert run["engine_version"] and run["prompt_bundle_version"] and run["config_digest"]
    assert board.get_board(pid).project.current_run_id == run["id"]
    with pytest.raises(RuntimeConflict, match="run_active"):
        start(rt, pid, key="different")
    with pytest.raises(RuntimeConflict, match="idempotency_conflict"):
        start(rt, pid, target="different")


def test_parallel_claim_has_only_one_winner(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    db, board, rt, pid, _ = runtime
    run = start(rt, pid)
    intent = plan(rt, pid, run)
    def attempt(worker):
        try:
            return claim(rt, pid, run, "explore", intent, worker)
        except RuntimeConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["a", "b"]))
    assert sum(item is not None for item in results) == 1
    grant = next(item for item in results if item)
    with db.connection() as conn:
        assert grant["lease_token"] not in "\n".join(conn.iterdump())


def test_reason_and_explore_are_mutually_exclusive(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    _, _, rt, pid, _ = runtime
    run = start(rt, pid)
    intent = plan(rt, pid, run)
    claim(rt, pid, run, "explore", intent)
    with pytest.raises(RuntimeConflict, match="tasks_busy"):
        claim(rt, pid, run)


def test_stop_racing_conclusion_is_atomic(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    _, board, rt, pid, _ = runtime
    run = start(rt, pid)
    intent = plan(rt, pid, run)
    grant = claim(rt, pid, run, "explore", intent)
    barrier = Barrier(2)
    body = result_body(grant, description="race observation")
    def conclude():
        barrier.wait()
        try:
            return rt.submit(pid, run["id"], grant["id"], body)
        except RuntimeConflict as exc:
            assert exc.code == "stale_run"
            return None
    def stop():
        barrier.wait()
        return rt.stop(pid, run["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        result_future, stop_future = pool.submit(conclude), pool.submit(stop)
        result = result_future.result()
        assert stop_future.result()["status"] == "stopping"
    current = board.get_board(pid)
    if result is None:
        assert len(current.facts) == 2 and current.intents[0].to_fact_id is None
    else:
        assert len(current.facts) == 3 and current.intents[0].to_fact_id == result["fact_id"]
        assert rt.submit(pid, run["id"], grant["id"], body) == result
    assert len(rt.pending_operations()) == 1


def test_parallel_explore_results_keep_both_conclusions(runtime):
    _, board, rt, pid, _ = runtime
    run = start(rt, pid)
    reason = claim(rt, pid, run)
    proposal = result_body(reason, intents=[
        {"from": ["origin"], "description": "one"}, {"from": ["origin"], "description": "two"},
    ])
    ids = rt.submit(pid, run["id"], reason["id"], proposal)["intent_ids"]
    grants = [claim(rt, pid, run, "explore", iid, f"worker-{n}") for n, iid in enumerate(ids)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda grant: rt.submit(pid, run["id"], grant["id"], result_body(grant, description=grant["id"])), grants))
    current = board.get_board(pid)
    assert len(current.facts) == 4 and current.revision == 4
    assert {i.to_fact_id for i in current.intents} == {r["fact_id"] for r in results}


def test_reason_snapshot_conflict_does_not_create_work(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    _, board, rt, pid, _ = runtime
    run = start(rt, pid)
    grant = claim(rt, pid, run)
    board.add_hint(pid, CreateHint(content="new information"))
    with pytest.raises(RuntimeConflict, match="revision_conflict"):
        rt.submit(pid, run["id"], grant["id"], result_body(grant, intents=[{"from": ["origin"], "description": "old plan"}]))
    assert board.get_board(pid).intents == []


@pytest.mark.parametrize("sources", [["goal"], ["missing"], ["origin", "origin"]])
def test_invalid_reason_sources_are_atomic(runtime, sources):
    from skidc.ctf.runtime import RuntimeConflict
    _, board, rt, pid, _ = runtime
    run = start(rt, pid)
    grant = claim(rt, pid, run)
    with pytest.raises(RuntimeConflict, match="invalid_sources"):
        rt.submit(pid, run["id"], grant["id"], result_body(grant, intents=[{"from": sources, "description": "invalid"}]))
    assert board.get_board(pid).intents == []


def test_duplicate_conclusion_returns_receipt_even_after_stop_and_expiry(runtime):
    from skidc.ctf.runtime import RuntimeStore, RuntimeConflict
    db, board, rt, pid, now = runtime
    run = start(rt, pid)
    intent = plan(rt, pid, run)
    grant = claim(rt, pid, run, "explore", intent)
    body = result_body(grant, description="Observed response")
    first = rt.submit(pid, run["id"], grant["id"], body)
    rt.stop(pid, run["id"])
    now[0] += 300
    restarted = RuntimeStore(db, clock=lambda: now[0])
    assert restarted.submit(pid, run["id"], grant["id"], body) == first
    current = board.get_board(pid)
    assert len(current.facts) == 3
    assert current.intents[0].to_fact_id == first["fact_id"]
    with pytest.raises(RuntimeConflict, match="idempotency_conflict"):
        restarted.submit(pid, run["id"], grant["id"], result_body(grant, description="different"))


def test_wrong_instance_or_token_cannot_write_or_read_receipt(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    _, _, rt, pid, _ = runtime
    run = start(rt, pid)
    grant = claim(rt, pid, run)
    body = result_body(grant, intents=[{"from": ["origin"], "description": "valid"}])
    rt.submit(pid, run["id"], grant["id"], body)
    for changes in ({"lease_token": "wrong"}, {"worker_instance_id": "other"}):
        with pytest.raises(RuntimeConflict):
            rt.submit(pid, run["id"], grant["id"], body.model_copy(update=changes))


def test_stop_persists_cleanup_and_blocks_resume_until_ack(runtime):
    from skidc.ctf.runtime import RuntimeConflict, RuntimeStore
    db, board, rt, pid, now = runtime
    run = start(rt, pid)
    grant = claim(rt, pid, run)
    stopped = rt.stop(pid, run["id"])
    assert stopped["status"] == "stopping" and stopped["cleanup_state"] == "pending"
    assert rt.stop(pid, run["id"]) == stopped
    with pytest.raises(RuntimeConflict, match="cleanup_required"):
        start(rt, pid, key="next")
    with pytest.raises(RuntimeConflict, match="stale_run"):
        rt.submit(pid, run["id"], grant["id"], result_body(grant, intents=[{"from": ["origin"], "description": "late"}]))
    restarted = RuntimeStore(db, clock=lambda: now[0])
    operation = restarted.pending_operations()[0]
    assert operation["run_id"] == run["id"] and operation["generation"] == 1
    restarted.confirm_cleanup(operation["id"])
    next_run = start(restarted, pid, key="next")
    assert next_run["id"] != run["id"] and next_run["generation"] == 2
    restarted.confirm_cleanup(operation["id"])
    assert restarted.get_run(pid, next_run["id"])["status"] == "running"
    with pytest.raises(RuntimeConflict, match="stale_run"):
        claim(restarted, pid, run)


def test_expired_lease_requires_cleanup_not_silent_reassignment(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    _, board, rt, pid, now = runtime
    run = start(rt, pid)
    grant = claim(rt, pid, run)
    before = board.get_board(pid).revision
    rt.heartbeat(pid, run["id"], grant["id"], grant["worker_instance_id"], grant["lease_token"])
    assert board.get_board(pid).revision == before
    now[0] = grant["lease_expires_at"]
    with pytest.raises(RuntimeConflict, match="lease_expired"):
        rt.heartbeat(pid, run["id"], grant["id"], grant["worker_instance_id"], grant["lease_token"])
    with pytest.raises(RuntimeConflict):
        claim(rt, pid, run)
    assert rt.reap_expired() == 1
    assert rt.reap_expired() == 0
    assert len(rt.pending_operations()) == 1
    assert rt.get_run(pid, run["id"])["status"] == "stopping"


def test_failure_does_not_create_fact_and_requires_cleanup(runtime):
    _, board, rt, pid, _ = runtime
    run = start(rt, pid)
    grant = claim(rt, pid, run)
    body = result_body(grant, error="execution result unknown")
    result = rt.submit(pid, run["id"], grant["id"], body)
    assert rt.submit(pid, run["id"], grant["id"], body) == result
    assert len(board.get_board(pid).facts) == 2
    assert rt.get_run(pid, run["id"])["status"] == "stopping"


def test_bootstrap_partial_observation_then_reason_only_once(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    _, board, rt, _, _ = runtime
    pid = board.create_project(CreateProject(title="bootstrap", origin="target", goal="solve")).project.id
    run = start(rt, pid)
    with pytest.raises(RuntimeConflict, match="bootstrap_pending"):
        claim(rt, pid, run)
    grant = claim(rt, pid, run, "bootstrap")
    rt.submit(pid, run["id"], grant["id"], result_body(grant, description="Partial progress"))
    with pytest.raises(RuntimeConflict, match="bootstrap_finished"):
        claim(rt, pid, run, "bootstrap")
    assert claim(rt, pid, run)["kind"] == "reason"


def test_target_cannot_be_reserved_twice_or_changed_on_resume(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    _, board, rt, pid, _ = runtime
    run = start(rt, pid)
    other = board.create_project(CreateProject(title="other", origin="target", goal="solve")).project.id
    with pytest.raises(RuntimeConflict, match="target_busy"):
        start(rt, other)
    rt.stop(pid, run["id"])
    with pytest.raises(RuntimeConflict, match="target_busy"):
        start(rt, other)
    rt.confirm_cleanup(rt.pending_operations()[0]["id"])
    with pytest.raises(RuntimeConflict, match="target_instance_mismatch"):
        start(rt, pid, key="next", target="reset-target")


def test_cross_project_task_and_fact_cannot_be_used(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    from skidc.ctf.store import ProjectNotFound
    db, board, rt, pid, _ = runtime
    other = board.create_project(CreateProject(title="other", origin="elsewhere", goal="solve")).project.id
    run = start(rt, pid)
    grant = claim(rt, pid, run)
    with pytest.raises(ProjectNotFound):
        rt.submit(other, run["id"], grant["id"], result_body(grant, description="wrong project"))
    with db.connection(write=True) as conn:
        conn.execute("INSERT INTO facts(project_id,id,description,created_at) VALUES(?, 'foreign', 'private', 'now')", (other,))
    with pytest.raises(RuntimeConflict, match="invalid_sources"):
        rt.submit(pid, run["id"], grant["id"], result_body(grant, intents=[{"from": ["foreign"], "description": "wrong project"}]))


def test_failed_transaction_leaves_no_result_or_receipt(runtime):
    db, board, rt, pid, _ = runtime
    run = start(rt, pid)
    intent = plan(rt, pid, run)
    grant = claim(rt, pid, run, "explore", intent)
    with db.connection(write=True) as conn:
        conn.execute("CREATE TRIGGER reject_observation BEFORE INSERT ON facts BEGIN SELECT RAISE(ABORT,'disk failure'); END")
    body = result_body(grant, description="result")
    with pytest.raises(sqlite3.IntegrityError):
        rt.submit(pid, run["id"], grant["id"], body)
    with db.connection(write=True) as conn:
        conn.execute("DROP TRIGGER reject_observation")
    result = rt.submit(pid, run["id"], grant["id"], body)
    assert len(board.get_board(pid).facts) == 3
    assert result["fact_id"]


def test_same_worker_name_does_not_reuse_old_lease_after_resume(runtime):
    from skidc.ctf.runtime import RuntimeConflict
    _, _, rt, pid, _ = runtime
    first_run = start(rt, pid)
    old = claim(rt, pid, first_run)
    rt.stop(pid, first_run["id"])
    rt.confirm_cleanup(rt.pending_operations()[0]["id"])
    new_run = start(rt, pid, key="next")
    new = claim(rt, pid, new_run)
    assert new["worker_instance_id"] == old["worker_instance_id"]
    assert new["lease_token"] != old["lease_token"]
    with pytest.raises(RuntimeConflict, match="lease_identity_mismatch"):
        rt.heartbeat(pid, new_run["id"], new["id"], old["worker_instance_id"], old["lease_token"])


@pytest.mark.parametrize("column,value", [("engine_version", "future-engine"), ("prompt_bundle_version", "future-prompts"), ("schema_version", 99)])
def test_incompatible_running_version_rejects_work_but_allows_cleanup(runtime, column, value):
    from skidc.ctf.runtime import RuntimeConflict
    db, _, rt, pid, _ = runtime
    run = start(rt, pid)
    with db.connection(write=True) as conn:
        conn.execute(f"UPDATE runs SET {column}=? WHERE id=?", (value, run["id"]))
    with pytest.raises(RuntimeConflict, match="runtime_version_mismatch"):
        claim(rt, pid, run)
    assert rt.stop(pid, run["id"])["status"] == "stopping"
    rt.confirm_cleanup(rt.pending_operations()[0]["id"])
    with pytest.raises(RuntimeConflict, match="runtime_version_mismatch"):
        start(rt, pid, key="next")


def test_failure_diagnostics_survive_restart(runtime):
    db, _, rt, pid, _ = runtime
    run = start(rt, pid)
    grant = claim(rt, pid, run)
    rt.submit(pid, run["id"], grant["id"], result_body(grant, error="connection lost after command"))
    with db.connection() as conn:
        assert conn.execute("SELECT last_error FROM task_attempts WHERE id=?", (grant["id"],)).fetchone()[0] == "connection lost after command"


def test_schema1_requires_explicit_copy_upgrade(tmp_path):
    from skidc.ctf.schema import SCHEMA_V1
    from skidc.ctf.db import APPLICATION_ID
    from skidc.ctf.upgrade import upgrade_copy

    source, dest = tmp_path / "v1.db", tmp_path / "v2.db"
    with sqlite3.connect(source) as conn:
        for statement in SCHEMA_V1:
            conn.execute(statement)
        conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
        conn.execute("PRAGMA user_version=1")
        conn.execute("INSERT INTO engine_metadata VALUES(1,'ctf',1)")
        conn.execute("INSERT INTO projects(id,title,bootstrap_enabled,created_at) VALUES('p1','old',0,'now')")
        conn.executemany("INSERT INTO facts(project_id,id,description,created_at) VALUES('p1',?,?,'now')", [("origin", "target"), ("goal", "solve")])
        conn.execute("INSERT INTO board_state VALUES('p1',1)")
    before = source.read_bytes()
    with pytest.raises(DatabaseCompatibilityError):
        CtfDatabase(source).initialize()
    upgrade_copy(source, dest)
    assert source.read_bytes() == before
    database = CtfDatabase(dest)
    database.initialize()
    assert BoardStore(database).get_board("p1").project.title == "old"
    with pytest.raises(FileExistsError):
        upgrade_copy(source, dest)
    assert source.read_bytes() == before
    from click.testing import CliRunner
    from skidc.ctf.cli import main
    cli_dest = tmp_path / "cli-v2.db"
    result = CliRunner().invoke(main, ["upgrade-copy", "--source", str(source), "--destination", str(cli_dest)])
    assert result.exit_code == 0, result.output
    assert BoardStore(CtfDatabase(cli_dest)).get_board("p1").project.title == "old"
    assert source.read_bytes() == before


@pytest.mark.parametrize("damage", ["missing_facts", "missing_board", "unknown_column"])
def test_copy_upgrade_failure_preserves_source_and_removes_incomplete_destination(tmp_path, damage):
    from skidc.ctf.schema import SCHEMA_V1
    from skidc.ctf.db import APPLICATION_ID
    from skidc.ctf.upgrade import upgrade_copy
    source, dest = tmp_path / "broken-v1.db", tmp_path / "new-v2.db"
    with sqlite3.connect(source) as conn:
        for statement in SCHEMA_V1:
            conn.execute(statement)
        conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
        conn.execute("PRAGMA user_version=1")
        conn.execute("INSERT INTO engine_metadata VALUES(1,'ctf',1)")
        conn.execute("INSERT INTO projects(id,title,bootstrap_enabled,created_at) VALUES('broken','missing origin',0,'now')")
        if damage != "missing_facts":
            conn.executemany("INSERT INTO facts(project_id,id,description,created_at) VALUES('broken',?,?,'now')", [("origin", "target"), ("goal", "solve")])
        if damage != "missing_board":
            conn.execute("INSERT INTO board_state VALUES('broken',1)")
        if damage == "unknown_column":
            conn.execute("ALTER TABLE hints ADD COLUMN unrecognized TEXT")
    before = source.read_bytes()
    with pytest.raises(DatabaseCompatibilityError):
        upgrade_copy(source, dest)
    assert source.read_bytes() == before
    assert not dest.exists()
