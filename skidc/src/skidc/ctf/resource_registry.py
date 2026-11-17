"""Durable local fencing journal, separate from short blackboard transactions."""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sqlite3


class ResourceConflict(RuntimeError):
    pass


class ResourceRegistry:
    APPLICATION_ID = 0x53435246

    def __init__(self, database_path, daemon_id):
        if not isinstance(daemon_id, str) or not daemon_id:
            raise ResourceConflict('Docker daemon identity required')
        database_path = str(Path(database_path).resolve())
        self.path = Path(database_path + '.execution.sqlite3')
        self.binding = (database_path, daemon_id)
        self.owner = sha256(json.dumps(self.binding).encode()).hexdigest()
        if self.path.exists():
            with self.connection(read_only=True) as conn:
                self._validate(conn)
        with self.connection(create=True, write=True) as conn:
            tables = conn.execute('SELECT name FROM sqlite_master').fetchall()
            if not tables:
                if conn.execute('PRAGMA application_id').fetchone()[0] or conn.execute('PRAGMA user_version').fetchone()[0]:
                    raise ResourceConflict('Foreign resource journal')
                conn.execute('CREATE TABLE metadata(database_path TEXT, daemon_id TEXT)')
                conn.execute('INSERT INTO metadata VALUES(?,?)', self.binding)
                conn.execute('CREATE TABLE runs(project TEXT, run TEXT, generation INTEGER, state TEXT, PRIMARY KEY(project,run))')
                conn.execute('''CREATE TABLE tasks(project TEXT, run TEXT, task TEXT, name TEXT UNIQUE,
                             phase INTEGER, state TEXT, container_id TEXT, PRIMARY KEY(project,run,task))''')
                conn.execute(f'PRAGMA application_id={self.APPLICATION_ID}')
                conn.execute('PRAGMA user_version=1')
            self._validate(conn)

    def _validate(self, conn):
        if (conn.execute('PRAGMA application_id').fetchone()[0] != self.APPLICATION_ID
                or conn.execute('PRAGMA user_version').fetchone()[0] != 1):
            raise ResourceConflict('Foreign resource journal')
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if tables != {'metadata', 'runs', 'tasks'}:
            raise ResourceConflict('Invalid resource journal schema')
        rows = conn.execute('SELECT database_path,daemon_id FROM metadata').fetchall()
        if len(rows) != 1 or tuple(rows[0]) != self.binding:
            raise ResourceConflict('Resource journal database/daemon mismatch')

    @contextmanager
    def connection(self, *, read_only=False, create=False, write=False):
        mode = 'ro' if read_only else ('rwc' if create else 'rw')
        conn = sqlite3.connect(f'{self.path.as_uri()}?mode={mode}', uri=True, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def name(self, scope):
        key = (self.owner, scope.mode, scope.project_id, scope.run_id, scope.generation, scope.task_id)
        return 'skidc-ctf-' + sha256(json.dumps(key).encode()).hexdigest()

    @staticmethod
    def _run(conn, scope, *, create=False):
        if create:
            conn.execute("INSERT OR IGNORE INTO runs VALUES(?,?,?,'open')",
                         (scope.project_id, scope.run_id, scope.generation))
        row = conn.execute('SELECT * FROM runs WHERE project=? AND run=?', (scope.project_id, scope.run_id)).fetchone()
        if row is None or row['generation'] != scope.generation or row['state'] != 'open':
            raise ResourceConflict('Run resources fenced')

    def reserve(self, scope):
        """Commit intention BEFORE external effects; ambiguous phases cannot replay."""
        with self.connection(write=True) as conn:
            self._run(conn, scope, create=True)
            row = conn.execute('SELECT * FROM tasks WHERE project=? AND run=? AND task=?',
                               (scope.project_id, scope.run_id, scope.task_id)).fetchone()
            if row is None:
                if scope.phase != 'execute':
                    raise ResourceConflict('Conclusion requires an existing execution')
                conn.execute("INSERT INTO tasks VALUES(?,?,?,?,1,'started',NULL)",
                             (scope.project_id, scope.run_id, scope.task_id, self.name(scope)))
                return 1
            if scope.phase != 'conclude' or row['phase'] != 1 or row['state'] != 'finished':
                raise ResourceConflict('Task phase cannot be replayed')
            conn.execute("UPDATE tasks SET phase=2,state='started' WHERE project=? AND run=? AND task=?",
                         (scope.project_id, scope.run_id, scope.task_id))
            return 2

    @contextmanager
    def start_guard(self, scope, phase):
        with self.connection(write=True) as conn:
            self._run(conn, scope)
            row = conn.execute('SELECT * FROM tasks WHERE project=? AND run=? AND task=?',
                               (scope.project_id, scope.run_id, scope.task_id)).fetchone()
            if row is None or row['phase'] != phase or row['state'] != 'started':
                raise ResourceConflict('Task resources fenced')
            yield conn, dict(row)

    def finish(self, scope, phase):
        with self.connection(write=True) as conn:
            conn.execute("UPDATE tasks SET state='finished' WHERE project=? AND run=? AND task=? AND phase=? AND state='started'",
                         (scope.project_id, scope.run_id, scope.task_id, phase))

    def fence_task(self, scope):
        with self.connection(write=True) as conn:
            conn.execute("INSERT OR IGNORE INTO runs VALUES(?,?,?,'open')", (scope.project_id, scope.run_id, scope.generation))
            conn.execute("INSERT OR IGNORE INTO tasks VALUES(?,?,?,?,0,'blocked',NULL)",
                         (scope.project_id, scope.run_id, scope.task_id, self.name(scope)))
            conn.execute("UPDATE tasks SET state='blocked' WHERE project=? AND run=? AND task=?",
                         (scope.project_id, scope.run_id, scope.task_id))

    def fence_run(self, pid, rid, generation):
        with self.connection(write=True) as conn:
            row = conn.execute('SELECT generation FROM runs WHERE project=? AND run=?', (pid, rid)).fetchone()
            if row is not None and row['generation'] != generation:
                raise ResourceConflict('Cleanup generation mismatch')
            conn.execute("INSERT OR IGNORE INTO runs VALUES(?,?,?,'closed')", (pid, rid, generation))
            conn.execute("UPDATE runs SET state='closed' WHERE project=? AND run=?", (pid, rid))

    def tasks(self, pid, rid):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM tasks WHERE project=? AND run=?', (pid, rid))]
