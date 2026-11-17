from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from threading import Event, Thread

import pytest
from docker.errors import NotFound

from skidc.ctf.db import CtfDatabase
from skidc.ctf.models import CreateProject
from skidc.ctf.runtime import RuntimeStore
from skidc.ctf.runtime_models import StartRun
from skidc.ctf.store import BoardStore
from skidc.ctf.task_runner import ExecutionScope


class Container:
    def __init__(self, manager, kwargs):
        self.manager, self.kwargs = manager, kwargs
        self.name = kwargs['name']
        self.id = f'id-{len(manager.created)}'
        self.attrs = {'Config': {'Labels': deepcopy(kwargs['labels'])}, 'State': {'Status': 'created'}}
        self.removed = False
        self.remove_fails = False

    def reload(self):
        pass

    def start(self):
        self.attrs['State']['Status'] = 'running'

    def remove(self, **kwargs):
        if self.remove_fails:
            raise ConnectionError('daemon unavailable')
        self.removed = True
        self.manager.items.pop(self.name, None)


class Containers:
    def __init__(self):
        self.items, self.created = {}, []
        self.after_create = None

    def get(self, key):
        for c in self.items.values():
            if key in (c.name, c.id):
                return c
        raise NotFound('missing')

    def create(self, **kwargs):
        if kwargs['name'] in self.items:
            raise RuntimeError('name conflict')
        self.created.append(kwargs)
        c = Container(self, kwargs)
        self.items[c.name] = c
        if self.after_create:
            self.after_create(c)
        return c

    def list(self, **kwargs):
        # Ignore filter intentionally: backend must check every result itself.
        return list(self.items.values())


class Docker:
    def __init__(self):
        self.containers = Containers()
        self.images = SimpleNamespace(get=lambda image: SimpleNamespace(id='sha256:trusted', attrs={'Config': {}}))
        self.daemon_id = 'daemon-1'

    def info(self):
        return {'ID': self.daemon_id}


class RawProcess:
    calls = []

    def __init__(self, container, argv, env):
        self.container, self.argv, self.env = container, argv, env

    def start(self):
        self.calls.append(self)

    def communicate(self, timeout):
        from skidc.execution.process import ProcessResult
        return ProcessResult(0, 'output', '')


@pytest.fixture
def setup(tmp_path):
    from skidc.ctf.docker_backend import CtfDockerBackend, ContainerSettings
    db = CtfDatabase(tmp_path / 'ctf.db')
    db.initialize()
    pid = BoardStore(db).create_project(CreateProject(title='test', origin='lab', goal='goal')).project.id
    now = [1000.0]
    runtime = RuntimeStore(db, clock=lambda: now[0])
    run = runtime.start(pid, StartRun(idempotency_key='s', target_instance_id='lab', scheduler={}))
    grant = runtime.claim_next(pid, run['id'], 'worker')
    scope = ExecutionScope(pid, run['id'], grant['task']['id'], run['generation'])
    docker = Docker()
    RawProcess.calls = []
    backend = CtfDockerBackend(runtime, ContainerSettings(image='test-image'), client=docker, process_type=RawProcess)
    return SimpleNamespace(db=db, rt=runtime, scope=scope, grant=grant, docker=docker, backend=backend, now=now)


def test_shared_process_identity_and_independent_import():
    from skidc.execution.process import ManagedProcess, ProcessResult
    from skidc.dispatcher.runtime.process import ManagedProcess as OldProcess, ProcessResult as OldResult
    assert ManagedProcess is OldProcess and ProcessResult is OldResult


def test_factory_is_lazy_and_task_home_and_credentials_are_isolated(setup):
    s = setup
    p = s.backend(s.scope, ['claude', '-p', 'prompt'], {'ANTHROPIC_AUTH_TOKEN': 'model-key'})
    assert not s.docker.containers.created
    p.start()
    config = s.docker.containers.created[0]
    assert config['name'].startswith('skidc-ctf-')
    assert config['labels']['io.skidc.mode'] == 'ctf'
    assert config['network_mode'] == 'none' and config['read_only']
    assert config['user'] == '1000:1000' and config['cap_drop'] == ['ALL']
    assert config['entrypoint'] == [] and config['working_dir'] == '/ctf-work'
    assert set(config['tmpfs']) == {'/ctf-home', '/ctf-work', '/tmp'}
    assert not config.get('volumes') and not config.get('ports')
    assert 'ANTHROPIC_AUTH_TOKEN' not in config['environment']
    assert RawProcess.calls[0].env == {'ANTHROPIC_AUTH_TOKEN': 'model-key'}
    assert p.communicate(1).returncode == 0


def test_conclude_uses_same_container_but_third_phase_is_rejected(setup):
    s = setup
    for phase in ('execute', 'conclude'):
        p = s.backend(replace(s.scope, phase=phase), ['command'], {})
        p.start()
        p.communicate(1)
    assert len(s.docker.containers.created) == 1
    assert RawProcess.calls[0].container is RawProcess.calls[1].container
    with pytest.raises(RuntimeError):
        s.backend(s.scope, ['command'], {}).start()


def test_restart_cannot_replay_execute_as_conclude(setup):
    from skidc.ctf.docker_backend import CtfDockerBackend, ContainerSettings
    s = setup
    p = s.backend(s.scope, ['command'], {})
    p.start()
    p.communicate(1)
    restarted = CtfDockerBackend(s.rt, ContainerSettings(image='test-image'), client=s.docker, process_type=RawProcess)
    with pytest.raises(RuntimeError):
        restarted(s.scope, ['command'], {}).start()
    assert len(RawProcess.calls) == 1


def test_runner_removes_task_container_before_publishing_success(setup):
    import json
    from skidc.ctf.task_runner import CtfTaskRunner
    from skidc.execution.base import WorkerSettings
    from skidc.execution.claudecode import ClaudeCodeDriver
    from skidc.execution.process import ProcessResult
    class Solved(RawProcess):
        def communicate(self, timeout):
            return ProcessResult(0, json.dumps({'fact': {'description': 'proof'}, 'complete': {'description': 'done'}}), '')
    s = setup
    s.backend.process_type = Solved
    runner = CtfTaskRunner(s.rt, ClaudeCodeDriver(), WorkerSettings('ctf', {}), s.backend)
    runner.worker_instance_id = 'worker'
    assert runner.run_grant(s.scope.project_id, s.scope.run_id, s.grant)['status'] == 'completed'
    assert not s.docker.containers.items
    op = s.rt.pending_operations()[0]
    assert s.backend.cleanup_operation(op['id'])['status'] == 'confirmed'


def test_rejected_worker_removes_background_processes(setup):
    from skidc.ctf.task_runner import CtfTaskRunner
    from skidc.execution.base import WorkerSettings
    from skidc.execution.claudecode import ClaudeCodeDriver
    from skidc.execution.process import ProcessResult
    class Rejected(RawProcess):
        def communicate(self, timeout):
            return ProcessResult(0, '{"accepted":false,"reason":"cannot do task"}', '')
    s = setup
    s.backend.process_type = Rejected
    runner = CtfTaskRunner(s.rt, ClaudeCodeDriver(), WorkerSettings('ctf', {}), s.backend)
    runner.worker_instance_id = 'worker'
    assert runner.run_grant(s.scope.project_id, s.scope.run_id, s.grant)['status'] == 'failed'
    assert not s.docker.containers.items


def test_failed_finalization_never_publishes_success(setup):
    from skidc.ctf.task_runner import CtfTaskRunner
    from skidc.execution.base import WorkerSettings
    from skidc.execution.claudecode import ClaudeCodeDriver
    from skidc.execution.process import ProcessResult
    class Solved(RawProcess):
        def communicate(self, timeout):
            self.container.remove_fails = True
            return ProcessResult(0, '{"fact":{"description":"proof"},"complete":{"description":"done"}}', '')
    s = setup
    s.backend.process_type = Solved
    runner = CtfTaskRunner(s.rt, ClaudeCodeDriver(), WorkerSettings('ctf', {}), s.backend)
    runner.worker_instance_id = 'worker'
    assert runner.run_grant(s.scope.project_id, s.scope.run_id, s.grant)['status'] == 'failed'
    board = BoardStore(s.db).get_board(s.scope.project_id)
    assert board.completion is None and len(board.facts) == 2
    assert s.rt.pending_operations()


def test_volume_declaring_image_never_creates_container(setup):
    s = setup
    s.docker.images.get = lambda name: SimpleNamespace(id='image', attrs={'Config': {'Volumes': {'/data': {}}}})
    with pytest.raises(RuntimeError):
        s.backend(s.scope, ['command'], {}).start()
    assert not s.docker.containers.created


def test_foreign_journal_is_not_modified(tmp_path):
    import sqlite3
    from skidc.ctf.resource_registry import ResourceRegistry
    path = tmp_path / 'ctf.db.execution.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE unrelated(value TEXT)')
    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        ResourceRegistry(tmp_path / 'ctf.db', 'daemon')
    assert path.read_bytes() == before


def test_resource_namespace_distinguishes_project_run_task_and_generation(setup):
    s = setup.scope
    variants = [s, replace(s, project_id='other'), replace(s, run_id='other'),
                replace(s, task_id='other'), replace(s, generation=2)]
    assert len({setup.backend.registry.name(v) for v in variants}) == 5
    assert setup.backend.registry.name(replace(s, phase='conclude')) == setup.backend.registry.name(s)


def test_unknown_create_absence_does_not_confirm_cleanup(setup):
    s = setup
    def uncertain(**kwargs):
        raise ConnectionError('unknown daemon outcome')
    s.docker.containers.create = uncertain
    with pytest.raises(ConnectionError):
        s.backend(s.scope, ['command'], {}).start()
    s.rt.stop(s.scope.project_id, s.scope.run_id)
    op = s.rt.pending_operations()[0]
    assert s.backend.cleanup_operation(op['id'])['status'] == 'pending'
    assert s.rt.pending_operations()


def test_pinned_container_id_mismatch_is_not_removed(setup):
    s = setup
    p = s.backend(s.scope, ['command'], {})
    p.start()
    c = next(iter(s.docker.containers.items.values()))
    c.id = 'replacement-id'
    s.rt.stop(s.scope.project_id, s.scope.run_id)
    op = s.rt.pending_operations()[0]
    assert s.backend.cleanup_operation(op['id'])['status'] == 'pending'
    assert not c.removed


@pytest.mark.parametrize('discovery', [True, False])
def test_renamed_pinned_container_never_acknowledges_cleanup(setup, discovery):
    s = setup
    s.backend(s.scope, ['command'], {}).start()
    c = next(iter(s.docker.containers.items.values()))
    del s.docker.containers.items[c.name]
    c.name = 'renamed-container'
    s.docker.containers.items[c.name] = c
    if not discovery:
        s.docker.containers.list = lambda **kwargs: []
    s.rt.stop(s.scope.project_id, s.scope.run_id)
    op = s.rt.pending_operations()[0]
    assert s.backend.cleanup_operation(op['id'])['status'] == 'pending'
    assert not c.removed and s.rt.pending_operations()


def test_duplicate_labeled_orphan_cannot_be_ignored_during_cleanup(setup):
    s = setup
    s.backend(s.scope, ['command'], {}).start()
    original = next(iter(s.docker.containers.items.values()))
    orphan = Container(s.docker.containers, {**original.kwargs, 'name': 'orphan-renamed'})
    orphan.id = 'orphan-id'
    s.docker.containers.items[orphan.name] = orphan
    s.rt.stop(s.scope.project_id, s.scope.run_id)
    op = s.rt.pending_operations()[0]
    assert s.backend.cleanup_operation(op['id'])['status'] == 'pending'
    assert not orphan.removed and s.rt.pending_operations()


@pytest.mark.parametrize('env', [{'CTF_CONTROL_TOKEN': 'secret'}, {'DOCKER_HOST': 'host'}, {'HOME': '/root'}])
def test_control_or_host_environment_rejected(setup, env):
    with pytest.raises(ValueError):
        setup.backend(setup.scope, ['command'], env)
    assert not setup.docker.containers.created


def test_expired_or_stopped_scope_never_creates_container(setup):
    s = setup
    s.now[0] += 31
    with pytest.raises(RuntimeError):
        s.backend(s.scope, ['command'], {}).start()
    assert not s.docker.containers.created


def test_cancel_before_start_is_sticky_and_never_starts(setup):
    p = setup.backend(setup.scope, ['command'], {})
    p.cancel('stop')
    with pytest.raises(RuntimeError):
        p.start()
    assert not setup.docker.containers.created


def test_cancel_removes_entire_task_container_and_blocks_resume(setup):
    s = setup
    p = s.backend(s.scope, ['command'], {})
    p.start()
    p.cancel('stop')
    assert not s.docker.containers.items
    with pytest.raises(RuntimeError):
        s.backend(s.scope, ['resume'], {}).start()


def test_create_response_loss_is_recoverable_but_never_replayed(setup):
    s = setup
    def lost(c):
        raise ConnectionError('lost create response')
    s.docker.containers.after_create = lost
    with pytest.raises(ConnectionError):
        s.backend(s.scope, ['command'], {}).start()
    with pytest.raises(RuntimeError):
        s.backend(s.scope, ['command'], {}).start()
    assert len(s.docker.containers.created) == 1
    s.rt.stop(s.scope.project_id, s.scope.run_id)
    op = s.rt.pending_operations()[0]
    assert s.backend.cleanup_operation(op['id'])['status'] == 'confirmed'
    assert not s.docker.containers.items


def test_cleanup_failure_keeps_operation_pending(setup):
    s = setup
    p = s.backend(s.scope, ['command'], {})
    p.start()
    next(iter(s.docker.containers.items.values())).remove_fails = True
    s.rt.stop(s.scope.project_id, s.scope.run_id)
    op = s.rt.pending_operations()[0]
    assert s.backend.cleanup_operation(op['id'])['status'] == 'pending'
    assert s.rt.pending_operations()
    with pytest.raises(RuntimeError):
        s.backend(s.scope, ['resume'], {}).start()


def test_cleanup_rejects_foreign_or_replaced_container(setup):
    s = setup
    p = s.backend(s.scope, ['command'], {})
    p.start()
    c = next(iter(s.docker.containers.items.values()))
    c.attrs['Config']['Labels']['io.skidc.mode'] = 'web'
    s.rt.stop(s.scope.project_id, s.scope.run_id)
    op = s.rt.pending_operations()[0]
    assert s.backend.cleanup_operation(op['id'])['status'] == 'pending'
    assert not c.removed


def test_restart_recovers_cleanup_and_retains_fence(setup):
    from skidc.ctf.docker_backend import CtfDockerBackend, ContainerSettings
    s = setup
    p = s.backend(s.scope, ['command'], {})
    p.start()
    s.rt.stop(s.scope.project_id, s.scope.run_id)
    op = s.rt.pending_operations()[0]
    restarted = CtfDockerBackend(s.rt, ContainerSettings(image='test-image'), client=s.docker, process_type=RawProcess)
    assert restarted.cleanup_operation(op['id'])['status'] == 'confirmed'
    assert not s.docker.containers.items
    with pytest.raises(RuntimeError):
        restarted(s.scope, ['resume'], {}).start()


def test_other_daemon_cannot_confirm_cleanup(setup):
    from skidc.ctf.docker_backend import CtfDockerBackend, ContainerSettings
    setup.docker.daemon_id = 'other-daemon'
    with pytest.raises(RuntimeError):
        CtfDockerBackend(setup.rt, ContainerSettings(image='test-image'), client=setup.docker)


def test_stop_during_create_serializes_cleanup_and_prevents_late_start(setup):
    s = setup
    creating, release, cleanup_done = Event(), Event(), Event()
    errors = []
    def delayed(c):
        creating.set()
        assert release.wait(3)
    s.docker.containers.after_create = delayed
    def start():
        try:
            s.backend(s.scope, ['command'], {}).start()
        except RuntimeError:
            pass  # Runtime stop may revoke authorization before exec.
        except Exception as exc:
            errors.append(exc)
    thread = Thread(target=start)
    thread.start()
    assert creating.wait(3)
    s.rt.stop(s.scope.project_id, s.scope.run_id)
    op = s.rt.pending_operations()[0]
    results = []
    def cleanup():
        results.append(s.backend.cleanup_operation(op['id']))
        cleanup_done.set()
    cleaner = Thread(target=cleanup)
    cleaner.start()
    assert not cleanup_done.wait(0.05)
    release.set()
    thread.join(3)
    cleaner.join(3)
    assert not errors and results == [{'id': op['id'], 'status': 'confirmed'}]
    assert not s.docker.containers.items
    with pytest.raises(RuntimeError):
        s.backend(s.scope, ['command'], {}).start()
