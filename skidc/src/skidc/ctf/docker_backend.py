"""Owned CTF task containers. No legacy container-name adoption or host mounts.

This local adapter intentionally defaults to no network and has no production CLI.
The controller owns Docker and the journal; workers never receive either handle.
"""
from dataclasses import dataclass
from math import isfinite
from threading import Lock

import docker
from docker.errors import NotFound

from skidc.execution.process import ManagedProcess
from .resource_registry import ResourceConflict, ResourceRegistry
from .task_runner import ExecutionScope


MODEL_ENV = frozenset({'OPENAI_API_KEY', 'CODEX_MODEL', 'CODEX_BASE_URL',
                       'ANTHROPIC_MODEL', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY'})


@dataclass(frozen=True, slots=True)
class ContainerSettings:
    image: str
    api_timeout: float = 5

    def __post_init__(self):
        if not isinstance(self.image, str) or not self.image.strip():
            raise ValueError('An explicit trusted local image is required')
        if isinstance(self.api_timeout, bool) or not isfinite(self.api_timeout) or not 0 < self.api_timeout <= 10:
            raise ValueError('Docker API timeout must be in (0, 10]')


class CtfDockerBackend:
    def __init__(self, runtime, settings, *, client=None, process_type=ManagedProcess):
        self.runtime, self.settings = runtime, settings
        self.client = client if client is not None else docker.from_env(timeout=settings.api_timeout)
        self._owns_client = client is None
        self.process_type = process_type
        self.registry = ResourceRegistry(runtime.database.path, self.client.info().get('ID'))

    def close(self):
        if self._owns_client:
            self.client.close()

    def _daemon(self):
        if self.client.info().get('ID') != self.registry.binding[1]:
            raise ResourceConflict('Docker daemon changed')

    def __call__(self, scope, argv, env):
        if (scope.mode != 'ctf' or scope.phase not in ('execute', 'conclude')
                or type(scope.generation) is not int or scope.generation < 1
                or any(not isinstance(v, str) or not v or len(v) > 256
                       for v in (scope.project_id, scope.run_id, scope.task_id))):
            raise ValueError('Invalid CTF execution scope')
        if not argv or any(not isinstance(v, str) or '\x00' in v for v in argv):
            raise ValueError('Expected a command argument list')
        if set(env) - MODEL_ENV or any(not isinstance(v, str) or '\x00' in v for v in env.values()):
            raise ValueError('Only explicit model environment is allowed')
        return OwnedProcess(self, scope, list(argv), dict(env))

    def labels(self, scope):
        return {'io.skidc.owner': self.registry.owner, 'io.skidc.mode': 'ctf',
                'io.skidc.project': scope.project_id, 'io.skidc.run': scope.run_id,
                'io.skidc.generation': str(scope.generation), 'io.skidc.task': scope.task_id}

    def _get(self, name):
        try:
            return self.client.containers.get(name)
        except NotFound:
            return None

    def _owned(self, container, scope, pinned_id=None):
        container.reload()
        labels = container.attrs.get('Config', {}).get('Labels') or {}
        if (container.name != self.registry.name(scope)
                or any(labels.get(k) != v for k, v in self.labels(scope).items())
                or pinned_id is not None and container.id != pinned_id):
            raise ResourceConflict('Container ownership mismatch')
        return container

    def _create(self, scope):
        image = self.client.images.get(self.settings.image)  # Never implicitly pull.
        if image.attrs.get('Config', {}).get('Volumes'):
            raise ResourceConflict('Images with declared volumes are not allowed')
        return self.client.containers.create(
            image=image.id, command=['sleep', 'infinity'], entrypoint=[],
            name=self.registry.name(scope), labels=self.labels(scope),
            network_mode='none', read_only=True, user='1000:1000', working_dir='/ctf-work',
            environment={'HOME': '/ctf-home', 'CODEX_HOME': '/ctf-home/.codex'},
            tmpfs={path: 'rw,nosuid,nodev,uid=1000,gid=1000,mode=0700,size=512m'
                   for path in ('/ctf-home', '/ctf-work', '/tmp')},
            cap_drop=['ALL'], security_opt=['no-new-privileges:true'],
            pids_limit=256, mem_limit='2g', nano_cpus=2_000_000_000,
            init=True, restart_policy={'Name': 'no'},
        )

    def _remove(self, scope, pinned_id=None, *, uncertain=False):
        container = self._get(self.registry.name(scope))
        if container is None:
            if pinned_id is not None and self._get(pinned_id) is not None:
                raise ResourceConflict('Pinned container still exists under a different name')
            # A timed-out create may still arrive at the daemon. Absence alone
            # does not prove cleanup of an unconfirmed creation request.
            return not uncertain
        self._owned(container, scope, pinned_id)
        cid = container.id
        # Pin the observed resource before destructive effects, including recovery
        # of a create whose response was lost. Keep this on removal response loss.
        with self.registry.connection(write=True) as conn:
            conn.execute('UPDATE tasks SET container_id=? WHERE project=? AND run=? AND task=?',
                         (cid, scope.project_id, scope.run_id, scope.task_id))
        try:
            container.remove(force=True, v=True)
        except NotFound:
            pass
        return self._get(cid) is None and self._get(self.registry.name(scope)) is None

    def cancel(self, scope):
        self.registry.fence_task(scope)
        self._daemon()
        row = next(r for r in self.registry.tasks(scope.project_id, scope.run_id) if r['task'] == scope.task_id)
        return self._remove(scope, row['container_id'], uncertain=row['phase'] > 0 and row['container_id'] is None)

    def finalize_task(self, scope):
        """Destroy background descendants before publishing a successful Fact."""
        return self.cancel(scope)

    def cleanup_operation(self, operation_id):
        op = next((o for o in self.runtime.pending_operations() if o['id'] == operation_id), None)
        if op is None:
            raise ResourceConflict('Expected an authoritative pending cleanup operation')
        pid, rid, generation = op['project_id'], op['run_id'], op['generation']
        run = self.runtime.get_run(pid, rid)
        if run['status'] != 'stopping' or run['generation'] != generation:
            raise ResourceConflict('Stale cleanup operation')
        # This commits after any in-flight start guard; subsequent starts cannot pass.
        self.registry.fence_run(pid, rid, generation)
        try:
            self._daemon()
            tasks = {r['task']: r for r in self.registry.tasks(pid, rid)}
            run_labels = {'io.skidc.owner': self.registry.owner, 'io.skidc.mode': 'ctf',
                          'io.skidc.project': pid, 'io.skidc.run': rid, 'io.skidc.generation': str(generation)}
            # Also discover resources after a journal restore or lost create response.
            for container in self.client.containers.list(all=True, filters={'label': [f'{k}={v}' for k, v in run_labels.items()]}):
                labels = container.attrs.get('Config', {}).get('Labels') or {}
                if all(labels.get(k) == v for k, v in run_labels.items()):
                    tid = labels.get('io.skidc.task')
                    if not tid:
                        raise ResourceConflict('Incomplete owned container labels')
                    pinned = tasks.get(tid, {}).get('container_id')
                    # Inspect every discovered ID, including duplicate task labels;
                    # a dict keyed by task alone must not hide a surviving orphan.
                    self._owned(container, ExecutionScope(pid, rid, tid, generation), pinned)
                    tasks.setdefault(tid, {'task': tid, 'container_id': container.id, 'phase': 1})
            for row in tasks.values():
                scope = ExecutionScope(pid, rid, row['task'], generation)
                if not self._remove(scope, row['container_id'], uncertain=row['phase'] > 0 and row['container_id'] is None):
                    return {'id': operation_id, 'status': 'pending'}
        except Exception:
            return {'id': operation_id, 'status': 'pending'}
        return self.runtime.confirm_cleanup(operation_id)


class OwnedProcess:
    def __init__(self, backend, scope, argv, env):
        self.backend, self.scope, self.argv, self.env = backend, scope, argv, env
        self.raw = None
        self.phase = None
        self.cancelled = False
        self._lock = Lock()

    def start(self):
        with self._lock:
            if self.cancelled or self.phase is not None:
                raise ResourceConflict('Process cannot start again')
            b, s = self.backend, self.scope
            b._daemon()
            b.runtime.authorize_execution(s)
            self.phase = b.registry.reserve(s)
            with b.registry.start_guard(s, self.phase) as (conn, row):
                b.runtime.authorize_execution(s)
                container = b._get(row['name'])
                if self.phase == 1:
                    if container is not None:
                        raise ResourceConflict('Refusing to adopt an existing container')
                    container = b._create(s)
                    b._owned(container, s)
                    container.start()
                else:
                    if container is None or row['container_id'] is None:
                        raise ResourceConflict('Original session container missing')
                    b._owned(container, s, row['container_id'])
                    if container.attrs.get('State', {}).get('Status') != 'running':
                        raise ResourceConflict('Original session container is not running')
                conn.execute('UPDATE tasks SET container_id=? WHERE project=? AND run=? AND task=?',
                             (container.id, s.project_id, s.run_id, s.task_id))
                b.runtime.authorize_execution(s)
                self.raw = b.process_type(container, self.argv, self.env)
                self.raw.start()

    def communicate(self, timeout):
        if self.raw is None:
            raise ResourceConflict('Process has not started')
        result = self.raw.communicate(timeout)
        if self.cancelled:
            result.cancelled = True
        if result.returncode == 0 and not result.cancelled and not result.timed_out:
            self.backend.registry.finish(self.scope, self.phase)
        else:
            self.cancel('worker_failed')
        return result

    def cancel(self, reason):
        with self._lock:
            self.cancelled = True
            if not self.backend.cancel(self.scope):
                raise ResourceConflict('Task cleanup remains unconfirmed')
