"""CTF protocol adapter over shared drivers and an injected execution backend.

The backend must create processes lazily, bound start/cancel calls, honor timeouts, and isolate
resources by ExecutionScope. This module does not provision containers or certify
cleanup. Gateway calls must be bounded; remote gateways normalize uncertain
transport failures to ConnectionError/TimeoutError.
"""
from dataclasses import dataclass, replace
from math import isfinite
from threading import Event, Lock, Thread
from uuid import uuid4

from skidc.execution.base import WorkerSettings

from .db import SCHEMA_VERSION
from .models import Board
from .prompting import render_task_prompt
from .runtime import ENGINE_VERSION, PROMPT_BUNDLE_VERSION, RuntimeConflict
from .runtime_models import TaskResult
from .store import ProjectNotFound
from .worker_contracts import WorkerRejected, build_task_result


@dataclass(frozen=True, slots=True)
class ExecutionScope:
    project_id: str
    run_id: str
    task_id: str
    generation: int
    mode: str = 'ctf'
    phase: str = 'execute'


@dataclass(frozen=True, slots=True)
class RunnerSettings:
    execute_seconds: float = 120
    conclude_seconds: float = 30
    heartbeat_seconds: float = 5
    submit_attempts: int = 2

    def __post_init__(self):
        for value in (self.execute_seconds, self.conclude_seconds, self.heartbeat_seconds):
            if isinstance(value, bool) or not isfinite(value) or value <= 0:
                raise ValueError('Runner time limits must be finite and positive')
        if self.heartbeat_seconds > 10:
            raise ValueError('Heartbeat must be at most 10 seconds')
        if type(self.submit_attempts) is not int or not 1 <= self.submit_attempts <= 5:
            raise ValueError('submit_attempts must be in 1..5')


class SubmissionPending(RuntimeError):
    """Retry the stored submission, never execute its worker again."""


class CtfTaskRunner:
    def __init__(self, gateway, driver, worker, process_factory, *, settings=None):
        self.gateway, self.driver, self.process_factory = gateway, driver, process_factory
        self.worker = WorkerSettings(worker.name, dict(worker.env))
        self.settings = settings or RunnerSettings()
        self.worker_instance_id = str(uuid4())
        self._pending = None
        self._executed = set()
        self._lock = Lock()

    def _check_run(self, pid, rid):
        run = self.gateway.get_run(pid, rid)
        if (run['engine_version'], run['schema_version'], run['prompt_bundle_version']) != (
                ENGINE_VERSION, SCHEMA_VERSION, PROMPT_BUNDLE_VERSION):
            raise ValueError('Unsupported CTF run version')
        if run['project_id'] != pid or run['id'] != rid:
            raise ValueError('Run identity mismatch')
        if run['scheduler'] is None:
            raise ValueError('CTF runner requires a scheduler-managed run')
        return run

    def step(self, pid, rid, *, cancel=None):
        """Run at most one task; parallelism requires separate runner instances."""
        with self._lock:
            if self._pending is not None:
                return self._flush(pid, rid)
            if cancel is not None and cancel.is_set():
                return {'status': 'cancelled'}
            run = self._check_run(pid, rid)
            if run['status'] != 'running':
                return {'status': run['status']}
            grant = self.gateway.claim_next(pid, rid, self.worker_instance_id)
            if grant['status'] != 'claimed':
                return grant
            return self._run_grant(pid, rid, grant, cancel=cancel)

    def run_grant(self, pid, rid, grant, *, cancel=None):
        with self._lock:
            if self._pending is not None:
                return self._flush(pid, rid)
            return self._run_grant(pid, rid, grant, cancel=cancel)

    def _heartbeat(self, pid, rid, task):
        try:
            self.gateway.heartbeat(pid, rid, task['id'], self.worker_instance_id, task['lease_token'])
            return True
        except Exception:
            # Unknown renewal outcomes are unsafe too. No model/secret diagnostics.
            return False

    @staticmethod
    def _cancel(process, reason):
        try:
            process.cancel(reason)
        except Exception:
            pass  # Durable cleanup remains unconfirmed regardless of local kill outcome.

    def _process(self, pid, rid, task, scope, argv, timeout, cancel):
        if not self._heartbeat(pid, rid, task):
            return None, 'lease_lost'
        if cancel is not None and cancel.is_set():
            return None, 'worker_cancelled'
        process = None
        done, lost = Event(), Event()
        start_gate = Lock()

        def monitor():
            while not done.wait(self.settings.heartbeat_seconds):
                if cancel is not None and cancel.is_set():
                    with start_gate:
                        self._cancel(process, 'worker_cancelled')
                    return
                if not self._heartbeat(pid, rid, task):
                    lost.set()
                    with start_gate:
                        self._cancel(process, 'lease_lost')
                    return

        watcher = None
        try:
            process = self.process_factory(scope, list(argv), dict(self.worker.env))
            # The factory must not start anything. Recheck after resource allocation.
            if not self._heartbeat(pid, rid, task):
                self._cancel(process, 'lease_lost')
                return None, 'lease_lost'
            if cancel is not None and cancel.is_set():
                self._cancel(process, 'worker_cancelled')
                return None, 'worker_cancelled'
            watcher = Thread(target=monitor, daemon=True, name='ctf-lease')
            # Never consume the only cancellation before start has created its
            # process handle. Backend start must have its own bounded timeout.
            with start_gate:
                watcher.start()
                process.start()
            result = process.communicate(timeout=timeout)
        except Exception:
            if process is not None:
                self._cancel(process, 'worker_process_error')
            return None, 'lease_lost' if lost.is_set() else 'worker_process_error'
        finally:
            done.set()
            if watcher is not None:
                watcher.join()
        if lost.is_set():
            return None, 'lease_lost'
        if cancel is not None and cancel.is_set() or result.cancelled:
            self._cancel(process, 'worker_cancelled')
            return None, 'worker_cancelled'
        if result.timed_out:
            self._cancel(process, 'worker_timeout')
            return None, 'worker_timeout'
        if result.returncode != 0:
            self._cancel(process, 'worker_exit_error')
            return None, 'worker_exit_error'
        return result, None

    def _run_grant(self, pid, rid, grant, *, cancel):
        task = grant['task']
        board = Board.model_validate(grant['board'])
        run = self._check_run(pid, rid)
        if (grant['status'] != 'claimed' or board.project.id != pid
                or board.project.current_run_id != rid or task['run_id'] != rid
                or task['worker_instance_id'] != self.worker_instance_id
                or task['base_revision'] != board.revision or task['generation'] != run['generation']):
            raise ValueError('Task and snapshot identity differ')
        if task['id'] in self._executed:
            raise ValueError('Task execution cannot be replayed')
        if not self._heartbeat(pid, rid, task):
            return {'status': 'lease_lost'}
        scope = ExecutionScope(pid, rid, task['id'], task['generation'])
        self._executed.add(task['id'])
        try:
            prompt = render_task_prompt(task['kind'], board, intent_id=task['intent_id'])
            command = self.driver.build_execute(self.worker, prompt, self.driver.prepare_session())
            result, error = self._process(pid, rid, task, scope, command.argv,
                                          self.settings.execute_seconds, cancel)
            if error:
                return self._fail(pid, rid, task, error)
            session = self.driver.extract_session(command.session, result.stdout, result.stderr)
            output = self.driver.extract_response_text(result.stdout, result.stderr)
            try:
                body = build_task_result(task, output, board)
            except WorkerRejected:
                return self._fail(pid, rid, task, 'worker_rejected')
            except ValueError:
                if task['kind'] == 'reason' or not session or not self.driver.supports_conclude():
                    return self._fail(pid, rid, task, 'worker_output_invalid')
                prompt = render_task_prompt(task['kind'], board, intent_id=task['intent_id'], phase='conclude')
                argv = self.driver.build_conclude(self.worker, prompt, session)
                result, error = self._process(pid, rid, task, replace(scope, phase='conclude'), argv,
                                              self.settings.conclude_seconds, cancel)
                if error:
                    return self._fail(pid, rid, task, error)
                output = self.driver.extract_response_text(result.stdout, result.stderr)
                body = build_task_result(task, output, board, phase='conclude')
            finalize = getattr(self.process_factory, 'finalize_task', None)
            if finalize is not None and not finalize(scope):
                return self._fail(pid, rid, task, 'worker_cleanup_pending')
        except SubmissionPending:
            raise
        except (RuntimeConflict, ProjectNotFound):
            return {'status': 'lease_lost'}
        except Exception:
            return self._fail(pid, rid, task, 'worker_adapter_error')
        return self._submit(pid, rid, task, body)

    def _fail(self, pid, rid, task, error):
        finalize = getattr(self.process_factory, 'finalize_task', None)
        if finalize is not None:
            try:
                if not finalize(ExecutionScope(pid, rid, task['id'], task['generation'])):
                    if error != 'lease_lost':
                        error = 'worker_cleanup_pending'
            except Exception:
                if error != 'lease_lost':
                    error = 'worker_cleanup_pending'
        if error == 'lease_lost':
            return {'status': 'lease_lost'}
        body = TaskResult(worker_instance_id=self.worker_instance_id, lease_token=task['lease_token'],
                          idempotency_key=f"result:{task['id']}", error=error)
        return self._submit(pid, rid, task, body)

    def _submit(self, pid, rid, task, body):
        self._pending = (pid, rid, task['id'], body)
        return self._flush(pid, rid)

    def _flush(self, pid, rid):
        if self._pending[:2] != (pid, rid):
            raise SubmissionPending('Resolve the pending run submission first')
        for _ in range(self.settings.submit_attempts):
            try:
                result = self.gateway.submit(*self._pending)
            except (ConnectionError, TimeoutError):
                continue
            except (RuntimeConflict, ProjectNotFound):
                self._pending = None
                return {'status': 'lease_lost'}
            except Exception:
                # Keep original body on unknown outcomes; never submit a new error.
                raise SubmissionPending('Result submission remains unresolved') from None
            self._pending = None
            return result
        raise SubmissionPending('Result submission remains unresolved') from None
