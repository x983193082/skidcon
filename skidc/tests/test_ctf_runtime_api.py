import pytest
import sqlite3
from fastapi.testclient import TestClient
from click.testing import CliRunner

from skidc.ctf.app import create_app

CONTROL = "control-0123456789-0123456789-0123456789"
DISPATCH = "dispatcher-0123456789-0123456789-0123456789"
RUNTIME = "runtime-0123456789-0123456789-0123456789"
PREFIX = "/api/ctf/v1"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "runtime.db", CONTROL, dispatcher_token=DISPATCH, runtime_token=RUNTIME)) as http:
        yield http


def call(client, method, path, token=CONTROL, body=None):
    return client.request(method, PREFIX + path, headers={"Authorization": f"Bearer {token}"}, json=body)


def setup_run(client):
    response = call(client, "POST", "/projects", body={"title": "CTF", "origin": "target", "goal": "solve", "bootstrap_enabled": False})
    assert response.status_code == 201, response.text
    pid = response.json()["project"]["id"]
    response = call(client, "POST", f"/projects/{pid}/runs", body={"idempotency_key": "start", "target_instance_id": "lab-instance"})
    assert response.status_code == 201, response.text
    return pid, response.json()["id"]


def test_runtime_api_requires_distinct_roles(client):
    pid, rid = setup_run(client)
    root = f"/projects/{pid}/runs/{rid}"
    for token in (CONTROL, RUNTIME):
        assert call(client, "POST", root + "/tasks/claim", token, {"kind": "reason", "worker_instance_id": "worker"}).status_code == 403
    for token in (DISPATCH, RUNTIME):
        assert call(client, "POST", root + "/stop", token).status_code == 403
        assert call(client, "POST", f"/projects/{pid}/hints", token, {"content": "clue"}).status_code == 403
        assert call(client, "POST", "/projects", token, {"title": "x", "origin": "x", "goal": "x"}).status_code == 403
    assert call(client, "GET", f"/projects/{pid}/board", DISPATCH).status_code == 200
    assert call(client, "GET", "/runtime/operations", CONTROL).status_code == 403
    assert call(client, "GET", "/runtime/operations", DISPATCH).status_code == 403


def test_bounded_claim_next_roles_and_consistent_snapshot(client):
    response = call(client, 'POST', '/projects', body={'title': 'ctf', 'origin': 'lab', 'goal': 'solve', 'bootstrap_enabled': False})
    pid = response.json()['project']['id']
    run = call(client, 'POST', f'/projects/{pid}/runs', body={
        'idempotency_key': 'scheduled', 'target_instance_id': 'lab', 'scheduler': {}}).json()
    root = f"/projects/{pid}/runs/{run['id']}"
    for token in (CONTROL, RUNTIME):
        assert call(client, 'POST', root + '/tasks/claim-next', token, {'worker_instance_id': 'w'}).status_code == 403
    assert call(client, 'POST', root + '/tasks/claim-next', DISPATCH, {'worker_instance_id': 'w', 'kind': 'explore'}).status_code == 422
    response = call(client, 'POST', root + '/tasks/claim-next', DISPATCH, {'worker_instance_id': 'w'})
    assert response.status_code == 200, response.text
    grant = response.json()
    assert grant['task']['kind'] == 'reason'
    assert grant['task']['base_revision'] == grant['board']['revision']
    task = grant['task']
    result = call(client, 'POST', root + f"/tasks/{task['id']}/result", DISPATCH, {
        'worker_instance_id': 'w', 'lease_token': task['lease_token'],
        'idempotency_key': 'result', 'no_op': True})
    assert result.status_code == 200, result.text
    assert call(client, 'POST', root + '/tasks/claim-next', DISPATCH, {'worker_instance_id': 'w'}).json()['status'] == 'waiting'
    assert client.get('/health').json()['execution_enabled'] is False


def test_http_completion_uses_dispatcher_lease_and_survives_cleanup(client):
    response = call(client, 'POST', '/projects', body={'title': 'ctf', 'origin': 'lab', 'goal': 'solve', 'bootstrap_enabled': True})
    pid = response.json()['project']['id']
    run = call(client, 'POST', f'/projects/{pid}/runs', body={'idempotency_key': 'start', 'target_instance_id': 'lab', 'scheduler': {}}).json()
    root = f"/projects/{pid}/runs/{run['id']}"
    task = call(client, 'POST', root + '/tasks/claim-next', DISPATCH, {'worker_instance_id': 'w'}).json()['task']
    payload = {'worker_instance_id': 'w', 'lease_token': task['lease_token'], 'idempotency_key': 'done',
               'bootstrap_complete': {'fact_description': 'proof', 'complete_description': 'satisfies goal'}}
    endpoint = root + f"/tasks/{task['id']}/result"
    assert call(client, 'POST', endpoint, CONTROL, payload).status_code == 403
    result = call(client, 'POST', endpoint, DISPATCH, payload)
    assert result.status_code == 200 and result.json()['status'] == 'completed'
    board = call(client, 'GET', f'/projects/{pid}/board').json()
    assert board['project']['status'] == 'completed'
    assert board['completion']['method'] == 'model_reasoned'
    assert board['completion']['from'] == [result.json()['fact_id']]
    assert call(client, 'POST', root + '/tasks/claim-next', DISPATCH, {'worker_instance_id': 'w'}).status_code == 409
    op = call(client, 'GET', '/runtime/operations', RUNTIME).json()[0]
    assert call(client, 'POST', f"/runtime/operations/{op['id']}/confirm", RUNTIME).status_code == 200
    assert call(client, 'POST', endpoint, DISPATCH, payload).json() == result.json()
    assert call(client, 'GET', f'/projects/{pid}/board').json()['project']['status'] == 'completed'


def test_http_results_fenced_and_cleanup_bound_to_runtime(client):
    pid, rid = setup_run(client)
    root = f"/projects/{pid}/runs/{rid}"
    grant = call(client, "POST", root + "/tasks/claim", DISPATCH, {"kind": "reason", "worker_instance_id": "worker"}).json()
    endpoint = root + f"/tasks/{grant['id']}/result"
    body = {"idempotency_key": "result", "lease_token": grant["lease_token"], "worker_instance_id": "worker", "intents": [{"from": ["origin"], "description": "inspect"}]}
    first = call(client, "POST", endpoint, DISPATCH, body)
    assert first.status_code == 200, first.text
    assert call(client, "POST", endpoint, DISPATCH, body).json() == first.json()
    call(client, "POST", root + "/stop")
    assert call(client, "POST", endpoint, DISPATCH, body).json() == first.json()
    assert call(client, "POST", endpoint, DISPATCH, {**body, "idempotency_key": "late"}).status_code == 409
    op = call(client, "GET", "/runtime/operations", RUNTIME).json()[0]
    for token in (CONTROL, DISPATCH):
        assert call(client, "POST", f"/runtime/operations/{op['id']}/confirm", token).status_code == 403
    assert call(client, "POST", f"/runtime/operations/{op['id']}/confirm", RUNTIME).status_code == 200
    resumed = call(client, "POST", f"/projects/{pid}/runs", body={"idempotency_key": "resume", "target_instance_id": "lab-instance"})
    assert resumed.status_code == 201 and resumed.json()["generation"] == 2
    assert client.get("/health").json()["execution_enabled"] is False
    assert client.get("/health").json()["runtime_protocol_enabled"] is True


@pytest.mark.parametrize("extra", [{"coverage_refs": []}, {"complete": {}}, {"evidence_refs": ["uncommitted-artifact"]}, {"mode": "real_website"}])
def test_runtime_rejects_web_completion_and_unbound_artifact_fields(client, extra):
    pid, rid = setup_run(client)
    root = f"/projects/{pid}/runs/{rid}"
    grant = call(client, "POST", root + "/tasks/claim", DISPATCH, {"kind": "reason", "worker_instance_id": "worker"}).json()
    body = {"idempotency_key": "r", "lease_token": grant["lease_token"], "worker_instance_id": "worker", "intents": [{"from": ["origin"], "description": "inspect"}], **extra}
    assert call(client, "POST", root + f"/tasks/{grant['id']}/result", DISPATCH, body).status_code == 422
    assert call(client, "GET", f"/projects/{pid}/board").json()["intents"] == []


@pytest.mark.parametrize("dispatcher,runtime", [(DISPATCH, None), (None, RUNTIME), (CONTROL, RUNTIME), (DISPATCH, DISPATCH), ("short", RUNTIME)])
def test_partial_or_reused_runtime_credentials_are_rejected(tmp_path, dispatcher, runtime):
    with pytest.raises(ValueError):
        create_app(tmp_path / "ctf.db", CONTROL, dispatcher_token=dispatcher, runtime_token=runtime)
    assert not (tmp_path / "ctf.db").exists()


def test_cli_accepts_explicit_runtime_tokens(tmp_path, monkeypatch):
    from skidc.ctf.cli import main
    import uvicorn

    files = []
    for name, token in (("control", CONTROL), ("dispatch", DISPATCH), ("runtime", RUNTIME)):
        file = tmp_path / name
        file.write_text(token)
        files.append(str(file))
    def run(app, **kwargs):
        with TestClient(app) as client:
            assert client.get("/health").json()["runtime_protocol_enabled"] is True
    monkeypatch.setattr(uvicorn, "run", run)
    result = CliRunner().invoke(main, ["serve", "--db-path", str(tmp_path / "ctf.db"), "--token-file", files[0], "--dispatcher-token-file", files[1], "--runtime-token-file", files[2]])
    assert result.exit_code == 0, result.output
    assert CONTROL not in result.output and DISPATCH not in result.output and RUNTIME not in result.output


def test_api_restart_recovers_expired_run_cleanup(tmp_path):
    path = tmp_path / "restart.db"
    with TestClient(create_app(path, CONTROL, dispatcher_token=DISPATCH, runtime_token=RUNTIME)) as first:
        pid, rid = setup_run(first)
        assert call(first, "POST", f"/projects/{pid}/runs/{rid}/tasks/claim", DISPATCH,
                    {"kind": "reason", "worker_instance_id": "lost-worker"}).status_code == 200
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE task_attempts SET lease_expires_at=0")
    with TestClient(create_app(path, CONTROL, dispatcher_token=DISPATCH, runtime_token=RUNTIME)) as restarted:
        assert call(restarted, "GET", f"/projects/{pid}/runs/{rid}").json()["status"] == "stopping"
        operations = call(restarted, "GET", "/runtime/operations", RUNTIME).json()
        assert len(operations) == 1 and operations[0]["run_id"] == rid
        assert call(restarted, "POST", "/runtime/reap-expired", RUNTIME).json()["stopped_runs"] == 0
