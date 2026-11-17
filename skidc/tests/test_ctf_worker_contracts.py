import json

import pytest

from skidc.ctf.db import CtfDatabase
from skidc.ctf.models import Board, CreateProject, Intent
from skidc.ctf.runtime import RuntimeStore
from skidc.ctf.runtime_models import StartRun
from skidc.ctf.store import BoardStore


@pytest.fixture
def env(tmp_path):
    db = CtfDatabase(tmp_path / 'ctf.db')
    db.initialize()
    board = BoardStore(db)
    pid = board.create_project(CreateProject(title='ctf', origin='test lab', goal='obtain proof', bootstrap_enabled=False)).project.id
    rt = RuntimeStore(db)
    rid = rt.start(pid, StartRun(idempotency_key='start', target_instance_id='lab', scheduler={}))['id']
    return db, board, rt, pid, rid


def parse(kind, data, board, **kwargs):
    from skidc.ctf.worker_contracts import parse_worker_result
    return parse_worker_result(kind, data, board=board, **kwargs)


def test_cairn_reason_accepts_wrapped_bare_and_singular_intents(env):
    board = env[1].get_board(env[3])
    intent = {'from': ['origin'], 'description': 'inspect target'}
    for payload in ({'accepted': True, 'data': {'intents': [intent]}}, {'intents': [intent]}, {'intent': intent}):
        assert parse('reason', json.dumps(payload), board) == {'intents': [intent]}


def test_cairn_reason_noop_requires_open_work(env):
    board = env[1].get_board(env[3])
    for payload in ({'accepted': True, 'data': {}}, {'intents': []}):
        with pytest.raises(ValueError, match='open Intent'):
            parse('reason', payload, board)
    board = board.model_copy(update={'intents': [
        Intent(id='i', description='existing', from_=['origin'], created_at='now')
    ]})
    assert parse('reason', {'intents': []}, board) == {'no_op': True}


@pytest.mark.parametrize('payload', [
    {'accepted': True, 'data': {'complete': {'from': ['goal'], 'description': 'claim'}}},
    {'accepted': True, 'data': {'intents': [{'from': ['missing'], 'description': 'bad'}]}},
    {'accepted': True, 'data': {'intents': [{'from': ['origin'], 'description': 'bad', 'coverage_refs': []}]}},
    {'accepted': True, 'data': {'no_op': True}},
    {'accepted': True, 'data': {'intents': []}, 'worker_instance_id': 'injected'},
    {'accepted': 'true', 'data': {'intents': []}},
    {'accepted': True, 'data': {'intents': [], 'complete': {'from': ['origin'], 'description': 'both'}}},
])
def test_worker_contract_rejects_cross_mode_identity_and_invalid_decisions(env, payload):
    with pytest.raises(ValueError):
        parse('reason', payload, env[1].get_board(env[3]))


def test_bootstrap_success_and_conclude_are_distinct(env):
    from skidc.ctf.worker_contracts import NeedsConclusion, WorkerRejected
    board = env[1].get_board(env[3])
    data = {'fact': {'description': 'observed proof'}, 'complete': {'description': 'goal met'}}
    assert parse('bootstrap', data, board) == {'bootstrap_complete': {'fact_description': 'observed proof', 'complete_description': 'goal met'}}
    assert parse('bootstrap', data, board, phase='conclude') == {'description': 'observed proof'}
    with pytest.raises(NeedsConclusion):
        parse('bootstrap', {'accepted': True, 'data': {'no_result': True}}, board)
    with pytest.raises(WorkerRejected):
        parse('bootstrap', {'accepted': False, 'reason': 'cannot execute'}, board)


def test_explore_outputs_one_fact_never_completes(env):
    board = env[1].get_board(env[3])
    assert parse('explore', {'description': 'negative finding: tested path failed'}, board) == {'description': 'negative finding: tested path failed'}
    for payload in ({'complete': {'from': ['origin'], 'description': 'claim'}}, {'description': 'fact', 'evidence_refs': ['unknown']}):
        with pytest.raises(ValueError):
            parse('explore', payload, board)


def test_worker_prompts_use_full_board_without_execution_identity(env):
    from skidc.ctf.prompting import render_task_prompt
    _, _, rt, pid, rid = env
    grant = rt.claim_next(pid, rid, 'secret-worker')
    prompt = render_task_prompt('reason', Board.model_validate(grant['board']))
    assert 'obtain proof' in prompt and 'test lab' in prompt
    assert 'Facts' in prompt and 'Intents' in prompt and 'Hints' in prompt
    assert grant['task']['lease_token'] not in prompt and 'secret-worker' not in prompt
    assert 'model_reasoned' in prompt


def test_simulated_cairn_reason_explore_complete_loop(env):
    from skidc.ctf.worker_contracts import build_task_result
    _, board, rt, pid, rid = env
    def respond(output):
        grant = rt.claim_next(pid, rid, 'worker-instance')
        body = build_task_result(grant['task'], output, Board.model_validate(grant['board']))
        return rt.submit(pid, rid, grant['task']['id'], body)
    reason = respond({'accepted': True, 'data': {'intents': [{'from': ['origin'], 'description': 'obtain evidence'}]}})
    assert len(reason['intent_ids']) == 1
    explored = respond({'accepted': True, 'data': {'description': 'Observed proof satisfying requested goal'}})
    result = respond({'accepted': True, 'data': {'complete': {'from': [explored['fact_id']], 'description': 'evidence meets goal'}}})
    assert result['status'] == 'completed'
    assert board.get_board(pid).completion.from_ == [explored['fact_id']]
    assert rt.get_run(pid, rid)['cleanup_state'] == 'pending'


def test_dispatcher_injects_identity_and_rejects_wrong_snapshot(env):
    from skidc.ctf.worker_contracts import build_task_result
    _, _, rt, pid, rid = env
    grant = rt.claim_next(pid, rid, 'trusted-worker')
    board = Board.model_validate(grant['board'])
    output = {'intents': [{'from': ['origin'], 'description': 'inspect'}]}
    body = build_task_result(grant['task'], output, board)
    assert body.worker_instance_id == 'trusted-worker'
    assert body.lease_token == grant['task']['lease_token']
    assert body.idempotency_key == f"result:{grant['task']['id']}"
    with pytest.raises(ValueError, match='snapshot'):
        build_task_result(grant['task'], output, board.model_copy(update={'revision': board.revision + 1}))


@pytest.mark.parametrize('solved', [True, False])
def test_simulated_cairn_bootstrap_solved_or_partial_then_reason(env, solved):
    from skidc.ctf.worker_contracts import build_task_result
    _, board, rt, _, _ = env
    pid = board.create_project(CreateProject(title='boot', origin='second lab', goal='prove', bootstrap_enabled=True)).project.id
    rid = rt.start(pid, StartRun(idempotency_key='boot', target_instance_id='second-lab', scheduler={}))['id']
    grant = rt.claim_next(pid, rid, 'worker')
    assert grant['task']['kind'] == 'bootstrap'
    output = {'accepted': True, 'data': {'fact': {'description': 'observed proof'}}}
    if solved:
        output['data']['complete'] = {'description': 'satisfies goal'}
    body = build_task_result(grant['task'], output, Board.model_validate(grant['board']), phase='execute' if solved else 'conclude')
    result = rt.submit(pid, rid, grant['task']['id'], body)
    assert result['status'] == ('completed' if solved else 'succeeded')
    if not solved:
        assert rt.claim_next(pid, rid, 'worker')['task']['kind'] == 'reason'
        assert board.get_board(pid).completion is None


def test_worker_parser_rejects_duplicate_json_keys(env):
    with pytest.raises(ValueError, match='Duplicate'):
        parse('reason', '{"intents":[],"intents":[]}', env[1].get_board(env[3]))
