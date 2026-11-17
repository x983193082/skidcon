import sqlite3
import hashlib
import json

import pytest

from skidc.ctf.db import APPLICATION_ID, CtfDatabase, DatabaseCompatibilityError
from skidc.ctf.runtime import RuntimeStore
from skidc.ctf.runtime_models import StartRun, TaskResult
from skidc.ctf.upgrade import upgrade_copy


def old_database(path, status='stopped', cleanup='confirmed'):
    from skidc.ctf.schema import SCHEMA_V2
    with sqlite3.connect(path) as conn:
        for statement in SCHEMA_V2:
            conn.execute(statement)
        conn.execute(f'PRAGMA application_id={APPLICATION_ID}')
        conn.execute('PRAGMA user_version=2')
        conn.execute("INSERT INTO engine_metadata VALUES(1,'ctf',2)")
        conn.execute("INSERT INTO projects(id,title,status,bootstrap_enabled,current_run_id,created_at) VALUES('p','old',?,0,'r','now')", ('stopped' if status == 'stopped' else 'active',))
        conn.executemany("INSERT INTO facts(project_id,id,description,created_at) VALUES('p',?,?,'now')", [('origin','lab'),('goal','solve')])
        conn.execute("INSERT INTO board_state VALUES('p',1)")
        conn.execute("""INSERT INTO runs VALUES('p','r',1,?,?,'lab','ctf-runtime-preview-1',2,
            'ctf-blackboard-v1','old-config','skipped',NULL,1000)""", (status, cleanup))


def test_schema2_copy_preserves_history_and_allows_new_generation(tmp_path):
    source, dest = tmp_path / 'old.db', tmp_path / 'new.db'
    old_database(source)
    before = source.read_bytes()
    with pytest.raises(DatabaseCompatibilityError):
        CtfDatabase(source).initialize()
    upgrade_copy(source, dest)
    assert source.read_bytes() == before
    rt = RuntimeStore(CtfDatabase(dest))
    assert rt.get_run('p', 'r')['schema_version'] == 2
    run = rt.start('p', StartRun(idempotency_key='resume', target_instance_id='lab'))
    assert run['schema_version'] == 4 and run['generation'] == 2


@pytest.mark.parametrize('status,cleanup', [('running','none'), ('stopping','pending'), ('stopped','pending')])
def test_schema2_copy_refuses_unclean_runtime(tmp_path, status, cleanup):
    source, dest = tmp_path / 'old.db', tmp_path / 'new.db'
    old_database(source, status, cleanup)
    before = source.read_bytes()
    with pytest.raises(DatabaseCompatibilityError, match='clean'):
        upgrade_copy(source, dest)
    assert source.read_bytes() == before and not dest.exists()


def test_migrated_receipts_replay_with_original_request_hash(tmp_path):
    source, dest = tmp_path / 'old.db', tmp_path / 'new.db'
    old_database(source)
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    start_payload = {'idempotency_key': 'original', 'target_instance_id': 'lab'}
    result_payload = {'worker_instance_id': 'w', 'lease_token': hashlib.sha256(b'token').hexdigest(),
                      'idempotency_key': 'result', 'intents': None, 'description': 'observed', 'error': None}
    with sqlite3.connect(source) as conn:
        conn.execute("INSERT INTO task_attempts VALUES('p','r','t','bootstrap',NULL,'w',?,1030,'succeeded',1,1000,NULL)", (result_payload['lease_token'],))
        conn.execute("INSERT INTO command_receipts VALUES('p','project','control','original',?,?)", (digest(start_payload), json.dumps({'id': 'r'})))
        conn.execute("INSERT INTO command_receipts VALUES('p','r','dispatcher','result',?,?)", (digest({'task_id': 't', 'payload': result_payload}), json.dumps({'task_id': 't', 'status': 'succeeded'})))
    upgrade_copy(source, dest)
    rt = RuntimeStore(CtfDatabase(dest))
    assert rt.start('p', StartRun(**start_payload)) == {'id': 'r'}
    assert rt.submit('p', 'r', 't', TaskResult(worker_instance_id='w', lease_token='token', idempotency_key='result', description='observed')) == {'task_id': 't', 'status': 'succeeded'}


def test_schema3_copy_preserves_scheduler_and_historical_versions(tmp_path):
    from skidc.ctf.schema import SCHEMA_V3
    source, dest = tmp_path / 'v3.db', tmp_path / 'v4.db'
    with sqlite3.connect(source) as conn:
        for statement in SCHEMA_V3:
            conn.execute(statement)
        conn.execute(f'PRAGMA application_id={APPLICATION_ID}')
        conn.execute('PRAGMA user_version=3')
        conn.execute("INSERT INTO engine_metadata VALUES(1,'ctf',3)")
        conn.execute("INSERT INTO projects(id,title,status,bootstrap_enabled,current_run_id,created_at) VALUES('p','old','stopped',0,'r','now')")
        conn.executemany("INSERT INTO facts(project_id,id,description,created_at) VALUES('p',?,?,'now')", [('origin','lab'),('goal','solve')])
        conn.execute("INSERT INTO board_state VALUES('p',1)")
        conn.execute("""INSERT INTO runs VALUES('p','r',1,'stopped','confirmed','lab','ctf-runtime-preview-2',3,
            'ctf-blackboard-v1','old-config','skipped',NULL,1000)""")
        conn.execute("INSERT INTO scheduler_state(project_id,run_id,policy,run_deadline,tasks_issued) VALUES('p','r','{}',2000,7)")
    before = source.read_bytes()
    upgrade_copy(source, dest)
    assert source.read_bytes() == before
    rt = RuntimeStore(CtfDatabase(dest))
    assert rt.get_run('p', 'r')['schema_version'] == 3
    assert rt.get_run('p', 'r')['scheduler']['tasks_issued'] == 7
    run = rt.start('p', StartRun(idempotency_key='resume', target_instance_id='lab', scheduler={}))
    assert run['schema_version'] == 4 and run['generation'] == 2
