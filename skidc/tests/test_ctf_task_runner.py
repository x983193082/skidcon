import json
from threading import Event
from types import SimpleNamespace

import pytest

from skidc.ctf.db import CtfDatabase
from skidc.ctf.models import CreateProject
from skidc.ctf.runtime import RuntimeStore
from skidc.ctf.runtime_models import StartRun
from skidc.ctf.store import BoardStore
from skidc.execution.base import WorkerSettings
from skidc.execution.claudecode import ClaudeCodeDriver


class Process:
    def __init__(self, output, action=None, **flags):
        self.result = SimpleNamespace(stdout=json.dumps(output) if isinstance(output, dict) else output,
                                      stderr='', returncode=flags.get('returncode', 0),
                                      timed_out=flags.get('timed_out', False), cancelled=False)
        self.action = action
        self.cancelled = Event()
        self.started = False

    def start(self):
        self.started = True

    def communicate(self, timeout):
        assert self.started
        if self.action:
            self.action(self)
        return self.result

    def cancel(self, reason):
        self.result.cancelled = True
        self.cancelled.set()


class Factory:
    def __init__(self, *processes):
        self.processes = list(processes)
        self.calls = []

    def __call__(self, scope, argv, env):
        self.calls.append((scope, argv, env))
        return self.processes.pop(0)


@pytest.fixture
def context(tmp_path):
    db = CtfDatabase(tmp_path / 'ctf.db')
    db.initialize()
    board = BoardStore(db)
    pid = board.create_project(CreateProject(title='ctf', origin='lab', goal='prove goal')).project.id
    now = [1000.0]
    rt = RuntimeStore(db, clock=lambda: now[0])
    rid = rt.start(pid, StartRun(idempotency_key='start', target_instance_id='lab', scheduler={}))['id']
    return db, board, rt, pid, rid, now


def make_runner(context, factory, gateway=None, **settings):
    from skidc.ctf.task_runner import CtfTaskRunner, RunnerSettings
    return CtfTaskRunner(gateway or context[2], ClaudeCodeDriver(),
                         WorkerSettings(name='ctf', env={'MODEL_KEY': 'model-only'}), factory,
                         settings=RunnerSettings(heartbeat_seconds=0.01, **settings))


SOLVED = {'accepted': True, 'data': {'fact': {'description': 'proof'}, 'complete': {'description': 'goal met'}}}


def test_task_runner_uses_shared_driver_and_injects_only_business_prompt(context):
    factory = Factory(Process(SOLVED))
    runner = make_runner(context, factory)
    result = runner.step(context[3], context[4])
    assert result['status'] == 'completed'
    scope, argv, env = factory.calls[0]
    assert scope.mode == 'ctf' and scope.project_id == context[3] and scope.run_id == context[4]
    assert not hasattr(scope, 'lease_token')
    assert argv[0] == 'claude' and 'Facts' in argv[-1]
    assert env == {'MODEL_KEY': 'model-only'}
    assert context[1].get_board(context[3]).completion.method == 'model_reasoned'


@pytest.mark.parametrize('output', [{'accepted': True, 'data': {'no_result': True}}, 'not JSON'])
def test_bootstrap_conclude_reuses_same_session_without_reexecuting(context, output):
    factory = Factory(Process(output), Process({'fact': {'description': 'partial observation'}}))
    runner = make_runner(context, factory)
    assert runner.step(context[3], context[4])['status'] == 'succeeded'
    first, second = factory.calls
    session = first[1][first[1].index('--session-id') + 1]
    assert second[1][1:3] == ['-r', session]
    assert first[0].task_id == second[0].task_id and first[0].run_id == second[0].run_id
    assert first[0].phase == 'execute' and second[0].phase == 'conclude'
    assert 'Do not re-execute' in second[1][-1]
    assert context[1].get_board(context[3]).project.status == 'active'


@pytest.mark.parametrize('flags', [{'timed_out': True}, {'returncode': 1}])
def test_uncertain_execution_stops_without_conclude_or_fake_fact(context, flags):
    factory = Factory(Process(SOLVED, **flags))
    runner = make_runner(context, factory)
    assert runner.step(context[3], context[4])['status'] == 'failed'
    assert len(factory.calls) == 1
    assert len(context[1].get_board(context[3]).facts) == 2
    assert context[2].pending_operations()


def test_expired_grant_never_creates_process(context):
    factory = Factory()
    runner = make_runner(context, factory)
    grant = context[2].claim_next(context[3], context[4], runner.worker_instance_id)
    context[5][0] += 31
    assert runner.run_grant(context[3], context[4], grant)['status'] == 'lease_lost'
    assert factory.calls == []


def test_heartbeat_observes_stop_and_cancels_process_without_writing_result(context):
    def stopped(process):
        context[2].stop(context[3], context[4])
        assert process.cancelled.wait(2)
    process = Process(SOLVED, action=stopped)
    factory = Factory(process)
    result = make_runner(context, factory).step(context[3], context[4])
    assert result['status'] == 'lease_lost'
    assert process.cancelled.is_set()
    assert len(context[1].get_board(context[3]).facts) == 2


class FlakyGateway:
    def __init__(self, rt, failures):
        self.rt, self.failures = rt, failures
        self.submissions = []
        self.claims = 0

    def __getattr__(self, name):
        return getattr(self.rt, name)

    def claim_next(self, *args):
        self.claims += 1
        return self.rt.claim_next(*args)

    def submit(self, *args):
        self.submissions.append(args[-1].model_dump())
        result = self.rt.submit(*args)
        if self.failures:
            self.failures -= 1
            raise ConnectionError('response lost')
        return result


def test_lost_success_response_retries_receipt_not_worker(context):
    gateway = FlakyGateway(context[2], 1)
    factory = Factory(Process(SOLVED))
    runner = make_runner(context, factory, gateway)
    assert runner.step(context[3], context[4])['status'] == 'completed'
    assert len(factory.calls) == 1 and gateway.claims == 1
    assert gateway.submissions[0] == gateway.submissions[1]
    assert len(context[1].get_board(context[3]).facts) == 3


def test_unresolved_submission_blocks_new_claims_and_can_be_retried(context):
    from skidc.ctf.task_runner import SubmissionPending
    gateway = FlakyGateway(context[2], 3)
    factory = Factory(Process(SOLVED))
    runner = make_runner(context, factory, gateway, submit_attempts=2)
    with pytest.raises(SubmissionPending):
        runner.step(context[3], context[4])
    assert runner.step(context[3], context[4])['status'] == 'completed'
    assert gateway.claims == 1 and len(factory.calls) == 1
    assert all(s == gateway.submissions[0] for s in gateway.submissions)


def test_runner_checks_bound_versions_before_claim(context):
    db, _, _, pid, rid, _ = context
    with db.connection(write=True) as conn:
        conn.execute("UPDATE runs SET prompt_bundle_version='other-mode' WHERE id=?", (rid,))
    factory = Factory()
    with pytest.raises(ValueError, match='version'):
        make_runner(context, factory).step(pid, rid)
    assert factory.calls == []


def test_cancel_before_start_does_not_create_worker(context):
    cancel = Event()
    cancel.set()
    factory = Factory()
    result = make_runner(context, factory).step(context[3], context[4], cancel=cancel)
    assert result['status'] == 'cancelled'
    assert factory.calls == []


def test_worker_rejection_is_not_conclude_fallback(context):
    factory = Factory(Process({'accepted': False, 'reason': 'cannot accept'}))
    assert make_runner(context, factory).step(context[3], context[4])['status'] == 'failed'
    assert len(factory.calls) == 1


def test_stop_during_start_cancels_after_start_not_before(context):
    import time

    class SlowStart(Process):
        cancelled_before_start = False

        def start(self):
            context[2].stop(context[3], context[4])
            time.sleep(0.08)
            self.started = True

        def cancel(self, reason):
            self.cancelled_before_start |= not self.started
            super().cancel(reason)

    process = SlowStart(SOLVED)
    assert make_runner(context, Factory(process)).step(context[3], context[4])['status'] == 'lease_lost'
    assert process.cancelled.is_set() and not process.cancelled_before_start


def test_process_exception_is_fixed_error_and_requires_cleanup(context):
    def broken(process):
        raise RuntimeError('secret API key must not be persisted')
    process = Process(SOLVED, action=broken)
    runner = make_runner(context, Factory(process))
    assert runner.step(context[3], context[4])['status'] == 'failed'
    assert process.cancelled.is_set()
    with context[0].connection() as conn:
        task = dict(conn.execute('SELECT * FROM task_attempts').fetchone())
        assert 'secret API' not in str(task)
    assert context[2].pending_operations()


def test_pending_submission_cannot_switch_projects(context):
    from skidc.ctf.task_runner import SubmissionPending
    gateway = FlakyGateway(context[2], 3)
    factory = Factory(Process(SOLVED))
    runner = make_runner(context, factory, gateway, submit_attempts=1)
    with pytest.raises(SubmissionPending):
        runner.step(context[3], context[4])
    with pytest.raises(SubmissionPending, match='pending run'):
        runner.step('another-project', 'another-run')
    assert gateway.claims == 1 and len(gateway.submissions) == 1


def test_reason_invalid_output_has_no_conclude(context):
    factory = Factory(Process({'no_result': True}), Process({'fact': {'description': 'partial'}}), Process('invalid'))
    runner = make_runner(context, factory)
    assert runner.step(context[3], context[4])['status'] == 'succeeded'
    assert runner.step(context[3], context[4])['status'] == 'failed'
    assert len(factory.calls) == 3


def test_already_executed_grant_cannot_be_replayed(context):
    factory = Factory(Process({'no_result': True}), Process({'fact': {'description': 'partial'}}))
    runner = make_runner(context, factory)
    grant = context[2].claim_next(context[3], context[4], runner.worker_instance_id)
    assert runner.run_grant(context[3], context[4], grant)['status'] == 'succeeded'
    with pytest.raises(ValueError, match='replayed'):
        runner.run_grant(context[3], context[4], grant)
    assert len(factory.calls) == 2


def test_cancel_during_execution_stops_without_conclude(context):
    cancel = Event()
    def cancelled(process):
        cancel.set()
        assert process.cancelled.wait(2)
    process = Process(SOLVED, action=cancelled)
    factory = Factory(process)
    assert make_runner(context, factory).step(context[3], context[4], cancel=cancel)['status'] == 'failed'
    assert len(factory.calls) == 1 and context[2].pending_operations()
