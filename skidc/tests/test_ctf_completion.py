import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from skidc.ctf.db import CtfDatabase
from skidc.ctf.models import CreateProject, CreateHint
from skidc.ctf.runtime import RuntimeStore, RuntimeConflict
from skidc.ctf.runtime_models import StartRun, ClaimTask, TaskResult
from skidc.ctf.store import BoardStore


@pytest.fixture
def env(tmp_path):
    db = CtfDatabase(tmp_path / 'ctf.db')
    db.initialize()
    board = BoardStore(db)
    pid = board.create_project(CreateProject(title='ctf', origin='lab', goal='prove the goal', bootstrap_enabled=True)).project.id
    now = [1000.0]
    rt = RuntimeStore(db, clock=lambda: now[0])
    rid = rt.start(pid, StartRun(idempotency_key='start', target_instance_id='lab'))['id']
    return db, board, rt, pid, rid, now


def claim(env, kind, intent=None):
    return env[2].claim(env[3], env[4], ClaimTask(kind=kind, intent_id=intent, worker_instance_id='worker'))


def submit(env, grant, key=None, **payload):
    return env[2].submit(env[3], env[4], grant['id'], TaskResult(worker_instance_id='worker', lease_token=grant['lease_token'], idempotency_key=key or grant['id'], **payload))


def partial(env):
    return submit(env, claim(env, 'bootstrap'), description='Observed condition matching the requested goal')['fact_id']


def complete_payload(fid):
    return {'from': [fid], 'description': 'The recorded observation satisfies the requested goal'}


def test_bootstrap_can_complete_atomically_and_cannot_resume(env):
    _, board, rt, pid, rid, now = env
    task = claim(env, 'bootstrap')
    payload = {'fact_description': 'Verified outcome', 'complete_description': 'Goal is satisfied by that outcome'}
    result = submit(env, task, bootstrap_complete=payload)
    assert result['status'] == 'completed'
    current = board.get_board(pid)
    assert current.project.status == 'completed'
    assert len(current.facts) == 3
    assert current.completion.from_ == [result['fact_id']]
    assert current.completion.to == 'goal'
    assert current.completion.method == 'model_reasoned'
    assert current.completion.revision == current.revision == 2
    assert rt.get_run(pid, rid)['cleanup_state'] == 'pending'
    now[0] += 100
    assert submit(env, task, bootstrap_complete=payload) == result
    rt.confirm_cleanup(rt.pending_operations()[0]['id'])
    assert board.get_board(pid).project.status == 'completed'
    with pytest.raises(RuntimeConflict, match='project_completed'):
        rt.start(pid, StartRun(idempotency_key='resume', target_instance_id='lab'))


def test_reason_completes_from_facts_and_cancels_unrelated_intents(env):
    _, board, rt, pid, _, _ = env
    fid = partial(env)
    submit(env, claim(env, 'reason'), intents=[{'from': ['origin'], 'description': 'optional branch'}])
    result = submit(env, claim(env, 'reason'), complete=complete_payload(fid))
    current = board.get_board(pid)
    assert result['status'] == 'completed'
    assert all(i.status == 'cancelled' for i in current.intents)
    assert len(current.facts) == 3
    assert current.completion.from_ == [fid]
    assert len(rt.pending_operations()) == 1


@pytest.mark.parametrize('sources', [['goal'], ['missing'], ['origin', 'origin']])
def test_completion_rejects_invalid_sources(env, sources):
    partial(env)
    task = claim(env, 'reason')
    before = env[1].get_board(env[3])
    with pytest.raises(RuntimeConflict, match='invalid_evidence'):
        submit(env, task, complete={'from': sources, 'description': 'claim'})
    assert env[1].get_board(env[3]) == before


@pytest.mark.parametrize('damage', ['retracted', 'foreign_target', 'uncommitted_artifact', 'missing_run'])
def test_completion_checks_evidence_validity_and_provenance(env, damage):
    db, board, _, pid, rid, _ = env
    fid = partial(env)
    task = claim(env, 'reason')
    with db.connection(write=True) as conn:
        if damage == 'retracted':
            conn.execute("UPDATE facts SET validity='retracted' WHERE project_id=? AND id=?", (pid, fid))
        elif damage == 'uncommitted_artifact':
            conn.execute("UPDATE facts SET evidence_refs='[\"unknown\"]' WHERE project_id=? AND id=?", (pid, fid))
        elif damage == 'missing_run':
            conn.execute("UPDATE facts SET created_run_id='missing' WHERE project_id=? AND id=?", (pid, fid))
        else:
            conn.execute("""INSERT INTO runs SELECT project_id,'other',2,'stopped','confirmed','different-target',
                engine_version,schema_version,prompt_bundle_version,config_digest,bootstrap_state,NULL,created_at
                FROM runs WHERE project_id=? AND id=?""", (pid, rid))
            conn.execute("UPDATE facts SET created_run_id='other' WHERE project_id=? AND id=?", (pid, fid))
    with pytest.raises(RuntimeConflict, match='invalid_evidence'):
        submit(env, task, complete=complete_payload(fid))
    assert board.get_board(pid).project.status == 'active'


@pytest.mark.parametrize('damage', ['ancestor', 'cycle'])
def test_completion_validates_entire_fact_dependency_chain(env, damage):
    db, _, _, pid, _, _ = env
    root = partial(env)
    iid = submit(env, claim(env, 'reason'), intents=[{'from': [root], 'description': 'derive'}])['intent_ids'][0]
    derived = submit(env, claim(env, 'explore', iid), description='derived evidence')['fact_id']
    with db.connection(write=True) as conn:
        if damage == 'ancestor':
            conn.execute("UPDATE facts SET validity='retracted' WHERE project_id=? AND id=?", (pid, root))
        else:
            conn.execute('UPDATE intent_sources SET fact_id=? WHERE project_id=? AND intent_id=?', (derived, pid, iid))
    with pytest.raises(RuntimeConflict, match='invalid_evidence'):
        submit(env, claim(env, 'reason'), complete=complete_payload(derived))


def test_explore_cannot_declare_completion(env):
    fid = partial(env)
    iid = submit(env, claim(env, 'reason'), intents=[{'from': ['origin'], 'description': 'explore'}])['intent_ids'][0]
    with pytest.raises(RuntimeConflict, match='result_kind_mismatch'):
        submit(env, claim(env, 'explore', iid), complete=complete_payload(fid))


def test_completion_with_stale_snapshot_is_rejected(env):
    fid = partial(env)
    task = claim(env, 'reason')
    env[1].add_hint(env[3], CreateHint(content='changed constraint'))
    with pytest.raises(RuntimeConflict, match='revision_conflict'):
        submit(env, task, complete=complete_payload(fid))


def test_bootstrap_completion_rolls_back_fact_if_receipt_fails(env):
    db, board, rt, pid, _, _ = env
    task = claim(env, 'bootstrap')
    with db.connection(write=True) as conn:
        conn.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON command_receipts BEGIN SELECT RAISE(ABORT,'failed'); END")
    payload = {'fact_description': 'result', 'complete_description': 'solved'}
    with pytest.raises(sqlite3.IntegrityError):
        submit(env, task, bootstrap_complete=payload)
    assert len(board.get_board(pid).facts) == 2
    assert board.get_board(pid).project.status == 'active'
    assert rt.pending_operations() == []
    with db.connection(write=True) as conn:
        conn.execute('DROP TRIGGER fail_receipt')
    assert submit(env, task, bootstrap_complete=payload)['status'] == 'completed'


def test_stop_racing_completion_never_half_commits(env):
    _, board, rt, pid, rid, _ = env
    fid = partial(env)
    task = claim(env, 'reason')
    barrier = Barrier(2)
    def finish():
        barrier.wait()
        try:
            return submit(env, task, complete=complete_payload(fid))
        except RuntimeConflict as exc:
            assert exc.code == 'stale_run'
            return None
    def stop():
        barrier.wait()
        return rt.stop(pid, rid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(finish), pool.submit(stop)
        result, _ = a.result(), b.result()
    current = board.get_board(pid)
    assert current.project.status == ('completed' if result else 'stopped')
    assert (current.completion is not None) == (result is not None)
    assert len(rt.pending_operations()) == 1


def test_bootstrap_with_new_hint_can_save_partial_observation_without_claiming_success(env):
    task = claim(env, 'bootstrap')
    env[1].add_hint(env[3], CreateHint(content='new goal context'))
    with pytest.raises(RuntimeConflict, match='revision_conflict'):
        submit(env, task, bootstrap_complete={'fact_description': 'old observation', 'complete_description': 'old decision'})
    assert len(env[1].get_board(env[3]).facts) == 2
    submit(env, task, description='Partial observation retained for fresh Reason')
    assert env[1].get_board(env[3]).project.status == 'active'
    assert claim(env, 'reason')['base_revision'] == 3


def test_completed_receipt_different_payload_is_conflict(env):
    task = claim(env, 'bootstrap')
    original = {'fact_description': 'observed proof', 'complete_description': 'goal satisfied'}
    submit(env, task, bootstrap_complete=original)
    with pytest.raises(RuntimeConflict, match='idempotency_conflict'):
        submit(env, task, bootstrap_complete={**original, 'complete_description': 'altered'})


def test_completion_cannot_use_another_projects_evidence(env):
    db, board, _, _, rid, _ = env
    partial(env)
    other = board.create_project(CreateProject(title='other', origin='other lab', goal='different')).project.id
    with db.connection(write=True) as conn:
        conn.execute("INSERT INTO facts(project_id,id,description,created_run_id,created_at) VALUES(?,'foreign','proof',?,'now')", (other, rid))
    with pytest.raises(RuntimeConflict, match='invalid_evidence'):
        submit(env, claim(env, 'reason'), complete=complete_payload('foreign'))
