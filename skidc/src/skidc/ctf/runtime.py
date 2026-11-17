"""Transactional execution protocol. No process/container operations occur here."""
import hashlib
import json
import secrets
import time
from uuid import uuid4

from .db import CtfDatabase, SCHEMA_VERSION
from .runtime_models import ClaimTask, StartRun, TaskResult
from .store import BoardStore, ProjectNotFound, _now
from .scheduler import Schedule
from .completion import InvalidEvidence, record_completion

ENGINE_VERSION = "ctf-runtime-preview-3"
PROMPT_BUNDLE_VERSION = "ctf-cairn-v2"
LEASE_SECONDS = 30


class RuntimeConflict(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _digest(value: dict) -> str:
    return _hash(json.dumps(value, sort_keys=True, separators=(",", ":")))


class RuntimeStore:
    def __init__(self, database: CtfDatabase, *, clock=time.time):
        self.database, self.clock = database, clock

    @staticmethod
    def _project(conn, pid):
        row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if row is None:
            raise ProjectNotFound(pid)
        return row

    @staticmethod
    def _run(conn, pid, rid):
        row = conn.execute("SELECT * FROM runs WHERE project_id=? AND id=?", (pid, rid)).fetchone()
        if row is None:
            raise ProjectNotFound(rid)
        return row

    @staticmethod
    def _compatible(run):
        if (run["engine_version"] != ENGINE_VERSION or run["schema_version"] != SCHEMA_VERSION
                or run["prompt_bundle_version"] != PROMPT_BUNDLE_VERSION):
            raise RuntimeConflict("runtime_version_mismatch")

    def _active(self, conn, pid, rid, *, check_version=True):
        run = self._run(conn, pid, rid)
        project = self._project(conn, pid)
        if project["current_run_id"] != rid or project["status"] != "active" or run["status"] != "running":
            raise RuntimeConflict("stale_run")
        if check_version:
            self._compatible(run)
        return run

    @staticmethod
    def _receipt(conn, pid, scope, actor, key, digest):
        row = conn.execute(
            "SELECT * FROM command_receipts WHERE project_id=? AND scope_id=? AND actor=? AND idempotency_key=?",
            (pid, scope, actor, key),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != digest:
            raise RuntimeConflict("idempotency_conflict")
        return json.loads(row["response"])

    @staticmethod
    def _save_receipt(conn, pid, scope, actor, key, digest, response):
        conn.execute("INSERT INTO command_receipts VALUES(?,?,?,?,?,?)", (pid, scope, actor, key, digest, json.dumps(response)))

    def start(self, pid: str, body: StartRun) -> dict:
        # Preserve pre-scheduler receipt hashes for copied schema-2 history.
        payload = body.model_dump()
        if body.scheduler is None:
            payload.pop('scheduler')
        digest = _digest(payload)
        with self.database.connection(write=True) as conn:
            project = self._project(conn, pid)
            receipt = self._receipt(conn, pid, "project", "control", body.idempotency_key, digest)
            if receipt is not None:
                return receipt
            if project['status'] == 'completed':
                raise RuntimeConflict('project_completed')
            previous = None
            if project["current_run_id"]:
                previous = self._run(conn, pid, project["current_run_id"])
                if previous["status"] == "stopping":
                    raise RuntimeConflict("cleanup_required")
                if previous["status"] != "stopped":
                    raise RuntimeConflict("run_active")
                if previous["cleanup_state"] != "confirmed":
                    raise RuntimeConflict("cleanup_required")
                if previous["target_instance_id"] != body.target_instance_id:
                    raise RuntimeConflict("target_instance_mismatch")
                # Explicit copy-upgrade keeps historical run versions intact.
                if (previous['engine_version'], previous['schema_version'], previous['prompt_bundle_version']) not in {
                    ('ctf-runtime-preview-1', 2, 'ctf-blackboard-v1'),
                    ('ctf-runtime-preview-2', 3, 'ctf-blackboard-v1'),
                }:
                    self._compatible(previous)
            if conn.execute("SELECT 1 FROM runs WHERE target_instance_id=? AND status IN ('running','stopping')", (body.target_instance_id,)).fetchone():
                raise RuntimeConflict("target_busy")
            rid = str(uuid4())
            generation = previous["generation"] + 1 if previous else 1
            bootstrap = previous["bootstrap_state"] if previous else ("pending" if project["bootstrap_enabled"] else "skipped")
            config_digest = _digest({"bootstrap_enabled": bool(project["bootstrap_enabled"]),
                                     "target_instance_id": body.target_instance_id,
                                     "scheduler": body.scheduler.model_dump() if body.scheduler is not None else None})
            conn.execute(
                """INSERT INTO runs(project_id,id,generation,status,cleanup_state,target_instance_id,
                   engine_version,schema_version,prompt_bundle_version,config_digest,bootstrap_state,created_at)
                   VALUES(?,?,?,'running','none',?,?,?,?,?,?,?)""",
                (pid, rid, generation, body.target_instance_id, ENGINE_VERSION, SCHEMA_VERSION,
                 PROMPT_BUNDLE_VERSION, config_digest, bootstrap, self.clock()),
            )
            conn.execute("UPDATE projects SET current_run_id=?,status='active' WHERE id=?", (rid, pid))
            if body.scheduler is not None:
                Schedule.create(conn, pid, rid, body.scheduler, self.clock())
            result = dict(self._run(conn, pid, rid))
            self._save_receipt(conn, pid, "project", "control", body.idempotency_key, digest, result)
            return result

    def get_run(self, pid: str, rid: str) -> dict:
        with self.database.connection() as conn:
            result = dict(self._run(conn, pid, rid))
            schedule = Schedule.load(conn, pid, rid)
            result['scheduler'] = None if schedule is None else {
                **{key: value for key, value in schedule.state.items()
                   if key not in ('project_id', 'run_id', 'policy', 'batch_ids')},
                'policy': schedule.policy.model_dump(),
                'batch_ids': json.loads(schedule.state['batch_ids']),
            }
            return result

    def claim(self, pid: str, rid: str, body: ClaimTask) -> dict:
        with self.database.connection(write=True) as conn:
            if Schedule.load(conn, pid, rid) is not None:
                raise RuntimeConflict('scheduler_managed')
            return self._claim(conn, pid, rid, body)

    def _claim(self, conn, pid, rid, body):
        run = self._active(conn, pid, rid)
        active = conn.execute("SELECT * FROM task_attempts WHERE project_id=? AND run_id=? AND status='leased'", (pid, rid)).fetchall()
        now = self.clock()
        if any(task["lease_expires_at"] <= now for task in active):
            raise RuntimeConflict("cleanup_required")
        if active and (body.kind != "explore" or any(t["kind"] != "explore" for t in active)):
            raise RuntimeConflict("tasks_busy")
        if body.kind != "bootstrap" and run["bootstrap_state"] == "pending":
            raise RuntimeConflict("bootstrap_pending")
        if body.kind == "bootstrap" and run["bootstrap_state"] != "pending":
            raise RuntimeConflict("bootstrap_finished")
        if body.kind == "explore":
            intent = conn.execute("SELECT * FROM intents WHERE project_id=? AND id=?", (pid, body.intent_id)).fetchone()
            if intent is None:
                raise ProjectNotFound(body.intent_id)
            if intent["status"] != "open" or intent["to_fact_id"] is not None or any(t["intent_id"] == body.intent_id for t in active):
                raise RuntimeConflict("intent_unavailable")
        revision = conn.execute("SELECT semantic_revision FROM board_state WHERE project_id=?", (pid,)).fetchone()[0]
        tid, token, expires = str(uuid4()), secrets.token_urlsafe(32), now + LEASE_SECONDS
        schedule = Schedule.load(conn, pid, rid)
        if schedule is not None:
            expires = schedule.lease_deadline(expires)
            if expires <= now:
                raise RuntimeConflict('deadline_expired')
        conn.execute(
            """INSERT INTO task_attempts(project_id,run_id,id,kind,intent_id,worker_instance_id,
               lease_token_hash,lease_expires_at,status,base_revision,created_at)
               VALUES(?,?,?,?,?,?,?,?,'leased',?,?)""",
            (pid, rid, tid, body.kind, body.intent_id, body.worker_instance_id, _hash(token), expires, revision, now),
        )
        return {"id": tid, "run_id": rid, "generation": run["generation"], "kind": body.kind,
                "intent_id": body.intent_id, "worker_instance_id": body.worker_instance_id,
                "lease_token": token, "lease_expires_at": expires, "base_revision": revision}

    def claim_next(self, pid, rid, worker):
        # Validate identity before consuming a scheduling budget.
        from .runtime_models import ClaimNext
        worker = ClaimNext(worker_instance_id=worker).worker_instance_id
        with self.database.connection(write=True) as conn:
            run = self._active(conn, pid, rid)
            schedule = Schedule.load(conn, pid, rid)
            if schedule is None:
                raise RuntimeConflict('scheduler_disabled')
            active = conn.execute("SELECT * FROM task_attempts WHERE project_id=? AND run_id=? AND status='leased'", (pid, rid)).fetchall()
            revision = conn.execute('SELECT semantic_revision FROM board_state WHERE project_id=?', (pid,)).fetchone()[0]
            decision = schedule.choose(run, active, revision, self.clock())
            if decision['status'] == 'stopping':
                self._stop(conn, pid, rid, decision['reason'])
            if decision['status'] != 'claimed':
                return decision
            task = self._claim(conn, pid, rid, ClaimTask(kind=decision['kind'], intent_id=decision['intent_id'], worker_instance_id=worker))
            return {'status': 'claimed', 'task': task,
                    'board': BoardStore._board(conn, pid).model_dump(by_alias=True)}

    @staticmethod
    def _identify_task(conn, pid, rid, tid, worker, token):
        task = conn.execute("SELECT * FROM task_attempts WHERE project_id=? AND run_id=? AND id=?", (pid, rid, tid)).fetchone()
        if task is None:
            raise ProjectNotFound(tid)
        if task["worker_instance_id"] != worker or not secrets.compare_digest(task["lease_token_hash"], _hash(token)):
            raise RuntimeConflict("lease_identity_mismatch")
        return task

    def _valid_lease(self, conn, pid, rid, task):
        self._active(conn, pid, rid)
        schedule = Schedule.load(conn, pid, rid)
        if schedule is not None and (reason := schedule.deadline_reason(self.clock())):
            raise RuntimeConflict(reason)
        if task["status"] != "leased":
            raise RuntimeConflict("lease_revoked")
        if task["lease_expires_at"] <= self.clock():
            raise RuntimeConflict("lease_expired")

    def heartbeat(self, pid, rid, tid, worker, token):
        with self.database.connection(write=True) as conn:
            task = self._identify_task(conn, pid, rid, tid, worker, token)
            self._valid_lease(conn, pid, rid, task)
            expires = self.clock() + LEASE_SECONDS
            schedule = Schedule.load(conn, pid, rid)
            if schedule is not None:
                expires = schedule.lease_deadline(expires)
            conn.execute("UPDATE task_attempts SET lease_expires_at=? WHERE project_id=? AND run_id=? AND id=?", (expires, pid, rid, tid))
            return {"lease_expires_at": expires}

    def authorize_execution(self, scope):
        """Local trusted backend gate; never exposed as a worker HTTP capability."""
        if scope.mode != 'ctf':
            raise RuntimeConflict('execution_mode_mismatch')
        with self.database.connection() as conn:
            run = self._active(conn, scope.project_id, scope.run_id)
            if run['generation'] != scope.generation:
                raise RuntimeConflict('execution_generation_mismatch')
            task = conn.execute('SELECT * FROM task_attempts WHERE project_id=? AND run_id=? AND id=?',
                                (scope.project_id, scope.run_id, scope.task_id)).fetchone()
            if task is None:
                raise RuntimeConflict('execution_task_missing')
            self._valid_lease(conn, scope.project_id, scope.run_id, task)
            return {'kind': task['kind']}

    def _stop(self, conn, pid, rid, reason):
        run = self._run(conn, pid, rid)
        if run["status"] in ("stopping", "stopped"):
            return dict(run)
        self._active(conn, pid, rid, check_version=False)
        conn.execute("UPDATE runs SET status='stopping',cleanup_state='pending',stop_reason=? WHERE project_id=? AND id=?", (reason, pid, rid))
        conn.execute("UPDATE projects SET status='stopped' WHERE id=?", (pid,))
        conn.execute("UPDATE task_attempts SET status='revoked' WHERE project_id=? AND run_id=? AND status='leased'", (pid, rid))
        conn.execute("INSERT INTO runtime_operations VALUES(?,?,?,?,'stop','pending',?)", (str(uuid4()), pid, rid, run["generation"], self.clock()))
        return dict(self._run(conn, pid, rid))

    def stop(self, pid, rid):
        with self.database.connection(write=True) as conn:
            return self._stop(conn, pid, rid, "manual_stop")

    def pending_operations(self):
        with self.database.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM runtime_operations WHERE status='pending' ORDER BY created_at,id")]

    def confirm_cleanup(self, operation_id):
        with self.database.connection(write=True) as conn:
            op = conn.execute("SELECT * FROM runtime_operations WHERE id=?", (operation_id,)).fetchone()
            if op is None:
                raise ProjectNotFound(operation_id)
            if op["status"] == "confirmed":
                return {"id": operation_id, "status": "confirmed"}
            run = self._run(conn, op["project_id"], op["run_id"])
            if run["generation"] != op["generation"] or run["status"] != "stopping":
                raise RuntimeConflict("stale_operation")
            conn.execute("UPDATE runtime_operations SET status='confirmed' WHERE id=?", (operation_id,))
            conn.execute("UPDATE runs SET status='stopped',cleanup_state='confirmed' WHERE project_id=? AND id=?", (op["project_id"], op["run_id"]))
            return {"id": operation_id, "status": "confirmed"}

    def reap_expired(self):
        with self.database.connection(write=True) as conn:
            stopped = set()
            for run in conn.execute("SELECT * FROM runs WHERE status='running'").fetchall():
                schedule = Schedule.load(conn, run['project_id'], run['id'])
                if schedule is not None and (reason := schedule.deadline_reason(self.clock())):
                    self._stop(conn, run['project_id'], run['id'], reason)
                    stopped.add((run['project_id'], run['id']))
            runs = conn.execute("""SELECT DISTINCT t.project_id,t.run_id FROM task_attempts t JOIN runs r
                ON r.project_id=t.project_id AND r.id=t.run_id
                WHERE t.status='leased' AND t.lease_expires_at<=? AND r.status='running'""", (self.clock(),)).fetchall()
            for run in runs:
                self._stop(conn, run["project_id"], run["run_id"], "lease_expired")
                stopped.add((run['project_id'], run['run_id']))
            return len(stopped)

    def _stale_reason(self, conn, pid, rid, tid, schedule):
        if schedule is None:
            raise RuntimeConflict('revision_conflict')
        conn.execute("UPDATE task_attempts SET status='failed',last_error='revision_conflict' WHERE project_id=? AND run_id=? AND id=?", (pid, rid, tid))
        reason = schedule.reason_conflict()
        if reason:
            self._stop(conn, pid, rid, reason)
        return {'task_id': tid, 'status': 'rejected', 'code': 'revision_conflict'}

    def _complete(self, conn, pid, rid, task, body, schedule):
        tid = task['id']
        is_bootstrap = body.bootstrap_complete is not None
        if (is_bootstrap and task['kind'] != 'bootstrap') or (not is_bootstrap and task['kind'] != 'reason'):
            raise RuntimeConflict('result_kind_mismatch')
        revision = conn.execute('SELECT semantic_revision FROM board_state WHERE project_id=?', (pid,)).fetchone()[0]
        if revision != task['base_revision']:
            if task['kind'] == 'reason':
                return self._stale_reason(conn, pid, rid, tid, schedule)
            raise RuntimeConflict('revision_conflict')
        result = {'task_id': tid}
        if is_bootstrap:
            fid = str(uuid4())
            conn.execute('INSERT INTO facts(project_id,id,description,created_run_id,created_at) VALUES(?,?,?,?,?)',
                         (pid, fid, body.bootstrap_complete.fact_description, rid, _now()))
            conn.execute("UPDATE runs SET bootstrap_state='done' WHERE project_id=? AND id=?", (pid, rid))
            sources, description = [fid], body.bootstrap_complete.complete_description
            result['fact_id'] = fid
        else:
            sources, description = body.complete.from_, body.complete.description
        try:
            cid = record_completion(conn, pid, rid, tid, sources, description, revision + 1, _now())
        except InvalidEvidence as exc:
            raise RuntimeConflict('invalid_evidence') from exc
        conn.execute("UPDATE task_attempts SET status='succeeded' WHERE project_id=? AND run_id=? AND id=?", (pid, rid, tid))
        conn.execute('UPDATE board_state SET semantic_revision=semantic_revision+1 WHERE project_id=?', (pid,))
        self._stop(conn, pid, rid, 'goal_completed')
        conn.execute("UPDATE projects SET status='completed' WHERE id=?", (pid,))
        result.update(status='completed', completion_id=cid, revision=revision + 1)
        return result

    def submit(self, pid: str, rid: str, tid: str, body: TaskResult) -> dict:
        payload = body.model_dump()
        if body.no_op is None:
            payload.pop('no_op')
        for field in ('complete', 'bootstrap_complete'):
            if payload[field] is None:
                payload.pop(field)
        payload["lease_token"] = _hash(body.lease_token)
        digest = _digest({"task_id": tid, "payload": payload})
        with self.database.connection(write=True) as conn:
            task = self._identify_task(conn, pid, rid, tid, body.worker_instance_id, body.lease_token)
            receipt = self._receipt(conn, pid, rid, "dispatcher", body.idempotency_key, digest)
            if receipt is not None:
                return receipt
            self._valid_lease(conn, pid, rid, task)
            schedule = Schedule.load(conn, pid, rid)
            if body.complete is not None or body.bootstrap_complete is not None:
                result = self._complete(conn, pid, rid, task, body, schedule)
                self._save_receipt(conn, pid, rid, 'dispatcher', body.idempotency_key, digest, result)
                return result
            result = {"task_id": tid}
            if body.error is not None:
                conn.execute("UPDATE task_attempts SET status='failed',last_error=? WHERE project_id=? AND run_id=? AND id=?", (body.error[:2000], pid, rid, tid))
                self._stop(conn, pid, rid, "task_failed")
                result["status"] = "failed"
            else:
                revision = conn.execute("SELECT semantic_revision FROM board_state WHERE project_id=?", (pid,)).fetchone()[0]
                if task["kind"] == "reason":
                    if body.intents is None and not (body.no_op is True and schedule is not None):
                        raise RuntimeConflict("result_kind_mismatch")
                    if revision != task["base_revision"]:
                        result = self._stale_reason(conn, pid, rid, tid, schedule)
                        self._save_receipt(conn, pid, rid, 'dispatcher', body.idempotency_key, digest, result)
                        return result
                    ids = []
                    for proposal in body.intents or []:
                        if len(set(proposal.from_)) != len(proposal.from_) or "goal" in proposal.from_:
                            raise RuntimeConflict("invalid_sources")
                        for fid in proposal.from_:
                            fact = conn.execute("SELECT validity FROM facts WHERE project_id=? AND id=?", (pid, fid)).fetchone()
                            if fact is None or fact["validity"] != "active":
                                raise RuntimeConflict("invalid_sources")
                        iid = str(uuid4())
                        conn.execute("INSERT INTO intents(project_id,id,description,created_run_id,created_at) VALUES(?,?,?,?,?)", (pid, iid, proposal.description, rid, _now()))
                        conn.executemany("INSERT INTO intent_sources VALUES(?,?,?)", [(pid, iid, fid) for fid in proposal.from_])
                        ids.append(iid)
                    result["intent_ids"] = ids
                else:
                    if body.description is None:
                        raise RuntimeConflict("result_kind_mismatch")
                    fid = str(uuid4())
                    conn.execute("INSERT INTO facts(project_id,id,description,source_intent_id,created_run_id,created_at) VALUES(?,?,?,?,?,?)", (pid, fid, body.description, task["intent_id"], rid, _now()))
                    if task["kind"] == "explore":
                        conn.execute("UPDATE intents SET to_fact_id=?,status='concluded' WHERE project_id=? AND id=?", (fid, pid, task["intent_id"]))
                    else:
                        conn.execute("UPDATE runs SET bootstrap_state='done' WHERE project_id=? AND id=?", (pid, rid))
                    result["fact_id"] = fid
                conn.execute("UPDATE task_attempts SET status='succeeded' WHERE project_id=? AND run_id=? AND id=?", (pid, rid, tid))
                if body.no_op is not True:
                    conn.execute("UPDATE board_state SET semantic_revision=semantic_revision+1 WHERE project_id=?", (pid,))
                    revision += 1
                result.update(status="succeeded", revision=revision)
                if schedule is not None:
                    if task['kind'] == 'reason':
                        reason = schedule.reason_succeeded(revision, self.clock())
                        if reason:
                            self._stop(conn, pid, rid, reason)
                    elif task['kind'] == 'explore':
                        schedule.explore_succeeded()
            self._save_receipt(conn, pid, rid, "dispatcher", body.idempotency_key, digest, result)
            return result
