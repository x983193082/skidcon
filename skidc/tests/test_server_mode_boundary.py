import pytest

from skidc.server import db


def create(http, mode="ctf"):
    response = http.post("/projects", json={"mode": mode, "title": "boundary", "origin": "target", "goal": "solve"})
    assert response.status_code == 201
    return response.json()["project"]["id"]


@pytest.mark.parametrize("path", ["coverage", "surfaces", "hypotheses"])
def test_web_resources_reject_ctf_projects(http_client, path):
    pid = create(http_client)
    response = http_client.get(f"/projects/{pid}/{path}")
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "engine_mismatch"
    assert http_client.get(f"/projects/{create(http_client, 'real_website')}/{path}").status_code == 200


@pytest.mark.parametrize("extra", [{"coverage_refs": []}, {"severity": "high"}, {"data": {"verify": True}}, {"verification_of": "origin"}, {"recon_category": "asset"}, {"unknown": True}])
@pytest.mark.parametrize("action", ["facts", "conclude"])
def test_ctf_fact_writes_reject_web_and_unknown_fields_atomically(http_client, extra, action):
    pid = create(http_client)
    path = f"/projects/{pid}/facts"
    payload = {"description": "Coverage is ordinary challenge text", **extra}
    if action == "conclude":
        intent = http_client.post(f"/projects/{pid}/intents", json={"from": ["origin"], "description": "observe", "creator": "w", "worker": "w"}).json()
        path = f"/projects/{pid}/intents/{intent['id']}/conclude"
        payload["worker"] = "w"
    before = http_client.get(f"/projects/{pid}").json()
    response = http_client.post(path, json=payload)
    assert response.status_code == 422, response.text
    assert http_client.get(f"/projects/{pid}").json() == before


@pytest.mark.parametrize("extra", [{"action_kind": "verify"}, {"surface_refs": []}, {"hypothesis_id": "h001"}, {"recon_complete": True}, {"mode": "real_website"}])
def test_ctf_intent_rejects_web_contract_and_mode_spoofing(http_client, extra):
    pid = create(http_client)
    response = http_client.post(f"/projects/{pid}/intents", json={"from": ["origin"], "description": "observe", "creator": "w", **extra})
    assert response.status_code == 422
    assert http_client.get(f"/projects/{pid}").json()["intents"] == []


@pytest.mark.parametrize("method,path,payload", [
    ("post", "phase/advance", {}), ("put", "phase", {"phase": "explore"}),
    ("put", "facts/origin", {"status": "verified"}),
    ("post", "coverage", {"item_type": "test", "description": "web"}),
    ("post", "coverage/reconcile", {}),
])
def test_ctf_cannot_invoke_web_mutations(http_client, method, path, payload):
    pid = create(http_client)
    before = http_client.get(f"/projects/{pid}").json()
    response = getattr(http_client, method)(f"/projects/{pid}/{path}", json=payload)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "engine_mismatch"
    assert http_client.get(f"/projects/{pid}").json() == before


def test_ctf_legacy_coverage_is_not_mutated_by_reconcile(http_client):
    from skidc.server.services import reconcile_project_coverage

    pid = create(http_client)
    with db.get_conn() as conn:
        conn.execute("INSERT INTO coverage_items (id, project_id, item_type, description, test_family, port, created_at, updated_at) VALUES ('c001', ?, 'legacy', 'old mixed data', 'crypto_transport', 80, 'old', 'old')", (pid,))
        before = dict(conn.execute("SELECT * FROM coverage_items WHERE project_id = ?", (pid,)).fetchone())
        assert reconcile_project_coverage(conn, pid) == 0
        assert dict(conn.execute("SELECT * FROM coverage_items WHERE project_id = ?", (pid,)).fetchone()) == before


@pytest.mark.parametrize("event", ["heartbeat", "release", "conclude", "failure", "expiry", "conclusion-failure"])
def test_ctf_lifecycle_does_not_modify_legacy_web_state(http_client, event):
    from skidc.server.services import expire_workers

    pid = create(http_client)
    intent = http_client.post(f"/projects/{pid}/intents", json={"from": ["origin"], "description": "observe", "creator": "w", "worker": "w"}).json()["id"]
    with db.get_conn() as conn:
        conn.execute("INSERT INTO coverage_items (id, project_id, item_type, description, execution_status, created_at, updated_at) VALUES ('c001', ?, 'legacy', 'old mixed data', 'testing', 'old', 'old')", (pid,))
        conn.execute("INSERT INTO coverage_intents (project_id, coverage_id, intent_id, created_at) VALUES (?, 'c001', ?, 'old')", (pid, intent))
        before = dict(conn.execute("SELECT * FROM coverage_items WHERE project_id = ?", (pid,)).fetchone())
        if event == "expiry":
            conn.execute("UPDATE intents SET last_heartbeat_at = '2000-01-01T00:00:00Z' WHERE project_id = ?", (pid,))
            expire_workers(conn, pid)
        elif event == "conclusion-failure":
            conn.execute("UPDATE intents SET execution_status = 'succeeded', conclusion_attempt_count = 2 WHERE project_id = ?", (pid,))
    if event != "expiry":
        payload = {"worker": "w"}
        if event == "conclude":
            payload["description"] = "objective observation"
        elif event == "failure":
            payload.update(error="timeout", max_attempts=1, backoff_seconds=0)
        elif event == "conclusion-failure":
            payload["error"] = "invalid result"
        response = http_client.post(f"/projects/{pid}/intents/{intent}/{event}", json=payload)
        assert response.status_code == 200, response.text
    with db.get_conn() as conn:
        assert dict(conn.execute("SELECT * FROM coverage_items WHERE project_id = ?", (pid,)).fetchone()) == before


def test_ctf_reason_identity_ignores_web_labels_but_tracks_evidence(http_client):
    from skidc.server.services import reason_state_fingerprint

    pid = create(http_client)
    with db.get_conn() as conn:
        before = reason_state_fingerprint(conn, pid)
        conn.execute("UPDATE projects SET phase = 'recon', recon_profile = '{}' WHERE id = ?", (pid,))
        conn.execute("UPDATE facts SET status = 'verified', recon_category = 'asset' WHERE project_id = ?", (pid,))
        assert reason_state_fingerprint(conn, pid) == before
        conn.execute("UPDATE facts SET evidence_refs = '[\"artifact-1\"]' WHERE project_id = ? AND id = 'origin'", (pid,))
        assert reason_state_fingerprint(conn, pid) != before


@pytest.mark.parametrize("mode,task_type", [("ctf", "verify"), ("real_website", "bootstrap")])
def test_task_log_cannot_claim_other_workflow(http_client, mode, task_type):
    pid = create(http_client, mode)
    response = http_client.post(f"/projects/{pid}/logs", json={"task_type": task_type, "worker_name": "w", "phase": task_type})
    assert response.status_code == 409
    assert http_client.get(f"/projects/{pid}/logs").json() == []


def test_web_writes_do_not_affect_a_ctf_project_with_the_same_local_ids(http_client):
    ctf = create(http_client)
    web = create(http_client, "real_website")
    before = http_client.get(f"/projects/{ctf}").json()
    written = http_client.post(f"/projects/{web}/facts", json={"description": "Web observation", "severity": "high"})
    assert written.status_code == 201
    assert http_client.get(f"/projects/{ctf}").json() == before
    assert http_client.post(f"/projects/{ctf}/intents", json={"from": [written.json()["id"]], "description": "foreign source", "creator": "w"}).status_code == 404
    assert http_client.get(f"/projects/{ctf}").json() == before
