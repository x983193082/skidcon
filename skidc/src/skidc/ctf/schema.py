"""Versioned CTF SQLite definitions; v1 remains for explicit copy-upgrades."""
SCHEMA_V1 = (
    """CREATE TABLE engine_metadata (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1), engine TEXT NOT NULL,
        schema_version INTEGER NOT NULL)""",
    """CREATE TABLE projects (
        id TEXT PRIMARY KEY, title TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'ctf' CHECK(mode='ctf'),
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status='draft'),
        origin_fact_id TEXT NOT NULL DEFAULT 'origin' CHECK(origin_fact_id='origin'),
        goal_fact_id TEXT NOT NULL DEFAULT 'goal' CHECK(goal_fact_id='goal'),
        goal_version INTEGER NOT NULL DEFAULT 1 CHECK(goal_version=1),
        bootstrap_enabled INTEGER NOT NULL CHECK(bootstrap_enabled IN (0,1)),
        current_run_id TEXT CHECK(current_run_id IS NULL), created_at TEXT NOT NULL,
        FOREIGN KEY(id, origin_fact_id) REFERENCES facts(project_id,id) DEFERRABLE INITIALLY DEFERRED,
        FOREIGN KEY(id, goal_fact_id) REFERENCES facts(project_id,id) DEFERRABLE INITIALLY DEFERRED)""",
    """CREATE TABLE facts (
        project_id TEXT NOT NULL REFERENCES projects(id), id TEXT NOT NULL,
        description TEXT NOT NULL, source_intent_id TEXT, created_run_id TEXT,
        evidence_refs TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
        validity TEXT NOT NULL DEFAULT 'active'
            CHECK(validity IN ('active','superseded','retracted','quarantined')),
        supersedes_fact_id TEXT, validity_reason TEXT, PRIMARY KEY(project_id,id),
        FOREIGN KEY(project_id, source_intent_id) REFERENCES intents(project_id,id),
        FOREIGN KEY(project_id, supersedes_fact_id) REFERENCES facts(project_id,id))""",
    """CREATE TABLE intents (
        project_id TEXT NOT NULL REFERENCES projects(id), id TEXT NOT NULL,
        description TEXT NOT NULL, to_fact_id TEXT,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','concluded','cancelled')),
        created_run_id TEXT, created_at TEXT NOT NULL, PRIMARY KEY(project_id,id),
        FOREIGN KEY(project_id, to_fact_id) REFERENCES facts(project_id,id))""",
    """CREATE TABLE intent_sources (
        project_id TEXT NOT NULL, intent_id TEXT NOT NULL, fact_id TEXT NOT NULL,
        PRIMARY KEY(project_id,intent_id,fact_id),
        FOREIGN KEY(project_id,intent_id) REFERENCES intents(project_id,id),
        FOREIGN KEY(project_id,fact_id) REFERENCES facts(project_id,id))""",
    """CREATE TABLE hints (
        project_id TEXT NOT NULL REFERENCES projects(id), id TEXT NOT NULL,
        content TEXT NOT NULL, creator TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(project_id,id))""",
    """CREATE TABLE board_state (
        project_id TEXT PRIMARY KEY REFERENCES projects(id),
        semantic_revision INTEGER NOT NULL CHECK(semantic_revision>=1))""",
)
TABLES_V1 = {"engine_metadata", "projects", "facts", "intents", "intent_sources", "hints", "board_state"}

_projects = SCHEMA_V1[1].replace("CHECK(status='draft')", "CHECK(status IN ('draft','active','stopped'))").replace(
    "current_run_id TEXT CHECK(current_run_id IS NULL)", "current_run_id TEXT"
).replace(
    "FOREIGN KEY(id, origin_fact_id)",
    "FOREIGN KEY(id,current_run_id) REFERENCES runs(project_id,id), FOREIGN KEY(id, origin_fact_id)",
)
SCHEMA_V2 = (SCHEMA_V1[0], _projects, *SCHEMA_V1[2:],
    """CREATE TABLE runs (
        project_id TEXT NOT NULL REFERENCES projects(id), id TEXT NOT NULL,
        generation INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('running','stopping','stopped')),
        cleanup_state TEXT NOT NULL CHECK(cleanup_state IN ('none','pending','confirmed')),
        target_instance_id TEXT NOT NULL, engine_version TEXT NOT NULL, schema_version INTEGER NOT NULL,
        prompt_bundle_version TEXT NOT NULL, config_digest TEXT NOT NULL,
        bootstrap_state TEXT NOT NULL CHECK(bootstrap_state IN ('pending','done','skipped')),
        stop_reason TEXT, created_at REAL NOT NULL,
        PRIMARY KEY(project_id,id), UNIQUE(project_id,generation))""",
    """CREATE UNIQUE INDEX one_active_target ON runs(target_instance_id)
        WHERE status IN ('running','stopping')""",
    """CREATE TABLE task_attempts (
        project_id TEXT NOT NULL, run_id TEXT NOT NULL, id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('bootstrap','reason','explore')), intent_id TEXT,
        worker_instance_id TEXT NOT NULL, lease_token_hash TEXT NOT NULL, lease_expires_at REAL NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('leased','succeeded','failed','revoked')),
        base_revision INTEGER NOT NULL, created_at REAL NOT NULL, last_error TEXT,
        PRIMARY KEY(project_id,run_id,id), FOREIGN KEY(project_id,run_id) REFERENCES runs(project_id,id),
        FOREIGN KEY(project_id,intent_id) REFERENCES intents(project_id,id))""",
    """CREATE UNIQUE INDEX one_intent_attempt ON task_attempts(project_id,intent_id)
        WHERE status='leased' AND intent_id IS NOT NULL""",
    """CREATE TABLE command_receipts (
        project_id TEXT NOT NULL REFERENCES projects(id), scope_id TEXT NOT NULL,
        actor TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL,
        response TEXT NOT NULL, PRIMARY KEY(project_id,scope_id,actor,idempotency_key))""",
    """CREATE TABLE runtime_operations (
        id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL, generation INTEGER NOT NULL,
        action TEXT NOT NULL CHECK(action='stop'), status TEXT NOT NULL CHECK(status IN ('pending','confirmed')),
        created_at REAL NOT NULL, FOREIGN KEY(project_id,run_id) REFERENCES runs(project_id,id),
        UNIQUE(project_id,run_id,action))""",
)
TABLES_V2 = TABLES_V1 | {"runs", "task_attempts", "command_receipts", "runtime_operations"}
SCHEMA_V3 = (*SCHEMA_V2,
    """CREATE TABLE scheduler_state (
        project_id TEXT NOT NULL, run_id TEXT NOT NULL, policy TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'reason' CHECK(phase IN ('reason','explore','waiting')),
        batch_ids TEXT NOT NULL DEFAULT '[]', batch_deadline REAL,
        run_deadline REAL NOT NULL, next_wakeup_at REAL,
        last_reasoned_revision INTEGER, no_progress_count INTEGER NOT NULL DEFAULT 0,
        conflict_count INTEGER NOT NULL DEFAULT 0, tasks_issued INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(project_id,run_id),
        FOREIGN KEY(project_id,run_id) REFERENCES runs(project_id,id))""",
)
TABLES_V3 = TABLES_V2 | {"scheduler_state"}
SCHEMA = tuple(statement.replace("CHECK(status IN ('draft','active','stopped'))",
                                 "CHECK(status IN ('draft','active','stopped','completed'))")
               for statement in SCHEMA_V3) + (
    """CREATE TABLE completions (
        project_id TEXT PRIMARY KEY REFERENCES projects(id), id TEXT NOT NULL UNIQUE,
        run_id TEXT NOT NULL, task_id TEXT NOT NULL, description TEXT NOT NULL,
        method TEXT NOT NULL CHECK(method='model_reasoned'),
        revision INTEGER NOT NULL, goal_version INTEGER NOT NULL CHECK(goal_version=1),
        created_at TEXT NOT NULL,
        FOREIGN KEY(project_id,run_id,task_id) REFERENCES task_attempts(project_id,run_id,id))""",
    """CREATE TABLE completion_sources (
        project_id TEXT NOT NULL REFERENCES completions(project_id), fact_id TEXT NOT NULL,
        PRIMARY KEY(project_id,fact_id),
        FOREIGN KEY(project_id,fact_id) REFERENCES facts(project_id,id))""",
)
TABLES = TABLES_V3 | {"completions", "completion_sources"}
