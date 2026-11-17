from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from skidc.ctf.db import CtfDatabase
from skidc.ctf.models import CreateHint, CreateProject
from skidc.ctf.runtime import RuntimeConflict, RuntimeStore
from skidc.ctf.runtime_models import ClaimTask, StartRun, TaskResult
from skidc.ctf.store import BoardStore


@pytest.fixture
def setup(tmp_path):
    db = CtfDatabase(tmp_path / 'ctf.db')
    db.initialize()
    board = BoardStore(db)
    pid = board.create_project(CreateProject(title='ctf', origin='lab', goal='solve', bootstrap_enabled=False)).project.id
    now = [1000.0]
    rt = RuntimeStore(db, clock=lambda: now[0])
    return db, board, rt, pid, now


def start(setup, **policy):
    _, _, rt, pid, _ = setup
    return rt.start(pid, StartRun(idempotency_key='start', target_instance_id='lab', scheduler=policy))['id']


def take(setup, rid, worker='worker'):
    return setup[2].claim_next(setup[3], rid, worker)


def submit(setup, rid, grant, **payload):
    task = grant['task']
    return setup[2].submit(setup[3], rid, task['id'], TaskResult(
        worker_instance_id=task['worker_instance_id'], lease_token=task['lease_token'],
        idempotency_key=task['id'], **payload))


def proposals(n):
    return [{'from': ['origin'], 'description': f'branch {i}'} for i in range(n)]


def test_bounded_batch_finishes_before_next_reason_and_snapshot_matches(setup):
    rid = start(setup, batch_size=2, max_parallel=2)
    reason = take(setup, rid)
    assert reason['status'] == 'claimed'
    assert reason['task']['kind'] == 'reason'
    assert reason['board']['revision'] == reason['task']['base_revision']
    assert reason['board']['project']['id'] == setup[3]
    assert {f['id'] for f in reason['board']['facts']} == {'origin', 'goal'}
    submit(setup, rid, reason, intents=proposals(4))
    one, two = take(setup, rid, 'a'), take(setup, rid, 'b')
    assert one['task']['intent_id'] != two['task']['intent_id']
    assert take(setup, rid)['status'] == 'waiting'
    submit(setup, rid, one, description='observed one')
    assert take(setup, rid)['status'] == 'waiting'
    submit(setup, rid, two, description='observed two')
    assert take(setup, rid)['task']['kind'] == 'reason'
    assert len([i for i in setup[1].get_board(setup[3]).intents if i.status == 'open']) == 2


def test_bootstrap_then_reason_and_no_manual_bypass(setup):
    db, _, rt, pid, _ = setup
    with db.connection(write=True) as conn:
        conn.execute('UPDATE projects SET bootstrap_enabled=1 WHERE id=?', (pid,))
    rid = start(setup)
    with pytest.raises(RuntimeConflict, match='scheduler_managed'):
        rt.claim(pid, rid, ClaimTask(kind='bootstrap', worker_instance_id='bypass'))
    grant = take(setup, rid)
    assert grant['task']['kind'] == 'bootstrap'
    assert take(setup, rid)['status'] == 'waiting'
    submit(setup, rid, grant, description='partial observations')
    assert take(setup, rid)['task']['kind'] == 'reason'


def test_concurrent_dispatchers_respect_parallel_limit(setup):
    rid = start(setup, max_parallel=1)
    submit(setup, rid, take(setup, rid), intents=proposals(3))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda w: take(setup, rid, w), ['a', 'b', 'c', 'd']))
    assert sum(r['status'] == 'claimed' for r in results) == 1


def test_noop_wait_and_budget_survive_restart_without_fake_revision(setup):
    db, board, rt, pid, now = setup
    rid = start(setup, no_progress_limit=2, wake_seconds=5)
    grant = take(setup, rid)
    first = submit(setup, rid, grant, no_op=True)
    assert first['status'] == 'succeeded'
    assert board.get_board(pid).revision == 1
    rt = RuntimeStore(db, clock=lambda: now[0])
    assert rt.claim_next(pid, rid, 'new')['status'] == 'waiting'
    now[0] += 5
    grant = rt.claim_next(pid, rid, 'new')
    second = submit(setup, rid, grant, no_op=True)
    assert rt.get_run(pid, rid)['stop_reason'] == 'no_progress_exhausted'
    assert submit(setup, rid, grant, no_op=True) == second
    assert len(rt.pending_operations()) == 1


def test_hint_wakes_wait_without_waiting_for_timer(setup):
    _, board, _, pid, _ = setup
    rid = start(setup)
    submit(setup, rid, take(setup, rid), no_op=True)
    assert take(setup, rid)['status'] == 'waiting'
    board.add_hint(pid, CreateHint(content='new clue'))
    grant = take(setup, rid)
    assert grant['task']['kind'] == 'reason'
    assert grant['board']['hints'][0]['content'] == 'new clue'


def test_revision_conflict_retries_fresh_snapshot_with_durable_limit(setup):
    db, board, rt, pid, now = setup
    rid = start(setup, conflict_limit=2)
    old = take(setup, rid)
    board.add_hint(pid, CreateHint(content='changed'))
    rejected = submit(setup, rid, old, intents=proposals(1))
    assert rejected['code'] == 'revision_conflict' and rejected['status'] == 'rejected'
    assert submit(setup, rid, old, intents=proposals(1)) == rejected
    rt = RuntimeStore(db, clock=lambda: now[0])
    fresh = rt.claim_next(pid, rid, 'fresh')
    assert fresh['board']['revision'] == 2
    board.add_hint(pid, CreateHint(content='changed again'))
    submit(setup, rid, fresh, intents=proposals(1))
    assert rt.get_run(pid, rid)['stop_reason'] == 'reason_conflicts_exhausted'
    assert board.get_board(pid).intents == []


@pytest.mark.parametrize('budget,reason', [({'run_seconds': 5}, 'run_deadline'), ({'batch_seconds': 5}, 'batch_deadline')])
def test_heartbeat_cannot_extend_hard_deadline(setup, budget, reason):
    _, _, rt, pid, now = setup
    rid = start(setup, **budget)
    submit(setup, rid, take(setup, rid), intents=proposals(1))
    grant = take(setup, rid)
    task = grant['task']
    renewed = rt.heartbeat(pid, rid, task['id'], task['worker_instance_id'], task['lease_token'])
    assert renewed['lease_expires_at'] <= now[0] + 5
    now[0] += 5
    with pytest.raises(RuntimeConflict):
        submit(setup, rid, grant, description='late observation')
    assert rt.reap_expired() == 1
    assert rt.get_run(pid, rid)['stop_reason'] == reason


def test_task_budget_does_not_reset_after_store_restart(setup):
    db, _, rt, pid, now = setup
    rid = start(setup, max_tasks=1)
    submit(setup, rid, take(setup, rid), intents=proposals(1))
    rt = RuntimeStore(db, clock=lambda: now[0])
    assert rt.claim_next(pid, rid, 'new')['status'] == 'stopping'
    assert rt.get_run(pid, rid)['stop_reason'] == 'task_budget_exhausted'


def test_idle_run_deadline_is_reaped_without_new_claim(setup):
    _, _, rt, pid, now = setup
    rid = start(setup, run_seconds=4)
    now[0] += 4
    assert rt.reap_expired() == 1
    assert rt.get_run(pid, rid)['stop_reason'] == 'run_deadline'


def test_manual_run_cannot_accidentally_enable_scheduler(setup):
    _, _, rt, pid, _ = setup
    rid = rt.start(pid, StartRun(idempotency_key='manual', target_instance_id='lab'))['id']
    with pytest.raises(RuntimeConflict, match='scheduler_disabled'):
        take(setup, rid)


def test_run_query_exposes_persisted_schedule_without_lease_secrets(setup):
    _, _, rt, pid, _ = setup
    rid = start(setup, max_tasks=7)
    grant = take(setup, rid)
    state = rt.get_run(pid, rid)['scheduler']
    assert state['policy']['max_tasks'] == 7
    assert state['tasks_issued'] == 1
    assert grant['task']['lease_token'] not in str(state)


def test_finished_batch_does_not_expire_while_dispatcher_is_idle(setup):
    _, _, rt, pid, now = setup
    rid = start(setup, batch_seconds=5)
    submit(setup, rid, take(setup, rid), intents=proposals(1))
    submit(setup, rid, take(setup, rid), description='finished')
    now[0] += 6
    assert rt.reap_expired() == 0
    assert take(setup, rid)['task']['kind'] == 'reason'


def test_noop_with_existing_intents_executes_remaining_batch(setup):
    rid = start(setup, batch_size=1, no_progress_limit=1)
    submit(setup, rid, take(setup, rid), intents=proposals(2))
    first = take(setup, rid)
    submit(setup, rid, first, description='first observed')
    submit(setup, rid, take(setup, rid), no_op=True)
    second = take(setup, rid)
    assert second['task']['kind'] == 'explore'
    assert second['task']['intent_id'] != first['task']['intent_id']


def test_failed_result_transaction_does_not_advance_schedule(setup):
    db, _, _, _, _ = setup
    rid = start(setup)
    grant = take(setup, rid)
    with db.connection(write=True) as conn:
        conn.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON command_receipts BEGIN SELECT RAISE(ABORT,'receipt unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError):
        submit(setup, rid, grant, intents=proposals(1))
    with db.connection(write=True) as conn:
        assert conn.execute('SELECT phase FROM scheduler_state').fetchone()[0] == 'reason'
        assert conn.execute('SELECT COUNT(*) FROM intents').fetchone()[0] == 0
        assert conn.execute('SELECT status FROM task_attempts').fetchone()[0] == 'leased'
        conn.execute('DROP TRIGGER reject_receipt')
    submit(setup, rid, grant, intents=proposals(1))
    assert take(setup, rid)['task']['kind'] == 'explore'


def test_failed_claim_does_not_consume_budget(setup):
    db, _, _, _, _ = setup
    rid = start(setup, max_tasks=1)
    with db.connection(write=True) as conn:
        conn.execute("CREATE TRIGGER reject_claim BEFORE INSERT ON task_attempts BEGIN SELECT RAISE(ABORT,'claim unavailable'); END")
    with pytest.raises(sqlite3.IntegrityError):
        take(setup, rid)
    with db.connection(write=True) as conn:
        assert conn.execute('SELECT tasks_issued FROM scheduler_state').fetchone()[0] == 0
        conn.execute('DROP TRIGGER reject_claim')
    assert take(setup, rid)['status'] == 'claimed'


def test_stop_resume_fences_old_scheduled_results(setup):
    _, _, rt, pid, _ = setup
    rid = start(setup)
    old = take(setup, rid)
    rt.stop(pid, rid)
    with pytest.raises(RuntimeConflict, match='cleanup_required'):
        rt.start(pid, StartRun(idempotency_key='resume', target_instance_id='lab', scheduler={}))
    rt.confirm_cleanup(rt.pending_operations()[0]['id'])
    new = rt.start(pid, StartRun(idempotency_key='resume', target_instance_id='lab', scheduler={}))
    assert new['generation'] == 2
    with pytest.raises(RuntimeConflict, match='stale_run'):
        submit(setup, rid, old, intents=proposals(1))
    assert take(setup, new['id'])['task']['kind'] == 'reason'


@pytest.mark.parametrize('payload', [{'max_tasks': 0}, {'max_parallel': 9}, {'wake_seconds': True}, {'batch_size': '4'}, {'web_mode': True}])
def test_scheduler_policy_rejects_invalid_or_cross_mode_config(payload):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        StartRun(idempotency_key='k', target_instance_id='lab', scheduler=payload)


@pytest.mark.parametrize('no_op', [False, 'true', 1])
def test_noop_requires_literal_true(no_op):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TaskResult(worker_instance_id='w', lease_token='t', idempotency_key='k', no_op=no_op)
