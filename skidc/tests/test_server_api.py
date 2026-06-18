from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_project_seeds_origin_and_goal(http_client: TestClient) -> None:
    r = http_client.post("/projects", json={"title": "t", "origin": "10.0.0.5", "goal": "root"})
    assert r.status_code == 201
    body = r.json()
    assert body["project"]["status"] == "active"
    assert [f["id"] for f in body["facts"]] == ["origin", "goal"]


def test_intent_claim_conclude_creates_fact(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    iid = http_client.post(
        f"/projects/{pid}/intents",
        json={"from": ["origin"], "description": "scan", "creator": "r", "worker": None},
    ).json()["id"]
    assert http_client.post(f"/projects/{pid}/intents/{iid}/heartbeat", json={"worker": "w1"}).status_code == 200
    r = http_client.post(f"/projects/{pid}/intents/{iid}/conclude", json={"worker": "w1", "description": "ports open"})
    assert r.status_code == 200
    assert r.json()["fact"]["id"] == "f001"
    detail = http_client.get(f"/projects/{pid}").json()
    assert [f["id"] for f in detail["facts"]] == ["origin", "goal", "f001"]


def test_claimed_intent_blocks_other_worker(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    iid = http_client.post(
        f"/projects/{pid}/intents",
        json={"from": ["origin"], "description": "x", "creator": "r", "worker": None},
    ).json()["id"]
    assert http_client.post(f"/projects/{pid}/intents/{iid}/heartbeat", json={"worker": "w1"}).status_code == 200
    # a different worker cannot steal an actively-claimed intent
    assert http_client.post(f"/projects/{pid}/intents/{iid}/heartbeat", json={"worker": "w2"}).status_code == 409


def test_complete_marks_project_completed(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    iid = http_client.post(
        f"/projects/{pid}/intents", json={"from": ["origin"], "description": "x", "creator": "r"},
    ).json()["id"]
    http_client.post(f"/projects/{pid}/intents/{iid}/heartbeat", json={"worker": "w1"})
    fid = http_client.post(f"/projects/{pid}/intents/{iid}/conclude", json={"worker": "w1", "description": "f"}).json()["fact"]["id"]
    assert http_client.post(f"/projects/{pid}/complete", json={"from": [fid], "description": "done", "worker": "w1"}).status_code == 200
    assert http_client.get(f"/projects/{pid}").json()["project"]["status"] == "completed"


def test_goal_cannot_be_used_as_intent_source(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    r = http_client.post(f"/projects/{pid}/intents", json={"from": ["goal"], "description": "x", "creator": "r"})
    assert r.status_code == 400


def test_reason_lease_claim_and_conflict(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    assert http_client.post(f"/projects/{pid}/reason/claim", json={"worker": "w1", "trigger": "initial"}).status_code == 200
    assert http_client.post(f"/projects/{pid}/reason/claim", json={"worker": "w2", "trigger": "initial"}).status_code == 409
    assert http_client.post(f"/projects/{pid}/reason/release", json={"worker": "w1"}).status_code == 200


def test_stop_clears_workers_and_blocks_writes(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    http_client.put(f"/projects/{pid}/status", json={"status": "stopped"})
    r = http_client.post(f"/projects/{pid}/intents", json={"from": ["origin"], "description": "x", "creator": "r"})
    assert r.status_code == 403


def test_hint_can_be_added(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    r = http_client.post(f"/projects/{pid}/hints", json={"content": "try default creds", "creator": "human"})
    assert r.status_code == 201
    assert http_client.get(f"/projects/{pid}").json()["hints"][0]["content"] == "try default creds"


def test_export_yaml_and_timeline(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    assert "project:" in http_client.get(f"/projects/{pid}/export?format=yaml").text
    assert "PROJECT CREATED" in http_client.get(f"/projects/{pid}/export?format=timeline").text


def test_conclude_persists_structured_fields(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    iid = http_client.post(
        f"/projects/{pid}/intents",
        json={"from": ["origin"], "description": "probe admin", "creator": "r", "worker": None},
    ).json()["id"]
    http_client.post(f"/projects/{pid}/intents/{iid}/heartbeat", json={"worker": "w1"})
    r = http_client.post(
        f"/projects/{pid}/intents/{iid}/conclude",
        json={
            "worker": "w1", "description": "IDOR confirmed on /admin",
            "scope": "api.example.com/admin", "vuln_type": "IDOR",
            "severity": "high", "parent_fact": "origin",
        },
    )
    assert r.status_code == 200
    fact = r.json()["fact"]
    assert fact["scope"] == "api.example.com/admin"
    assert fact["vuln_type"] == "IDOR"
    assert fact["severity"] == "high"
    assert fact["parent_fact"] == "origin"
    # round-trips through get_project and export
    detail_fact = next(f for f in http_client.get(f"/projects/{pid}").json()["facts"] if f["id"] == fact["id"])
    assert detail_fact["severity"] == "high"
    yaml_text = http_client.get(f"/projects/{pid}/export?format=yaml").text
    assert "IDOR" in yaml_text


def _seed_fact(http_client: TestClient, pid: str, description: str) -> str:
    iid = http_client.post(
        f"/projects/{pid}/intents",
        json={"from": ["origin"], "description": "probe", "creator": "r", "worker": None},
    ).json()["id"]
    http_client.post(f"/projects/{pid}/intents/{iid}/heartbeat", json={"worker": "w1"})
    return http_client.post(
        f"/projects/{pid}/intents/{iid}/conclude",
        json={"worker": "w1", "description": description},
    ).json()["fact"]["id"]


def test_attack_path_create_list_delete(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    f1 = _seed_fact(http_client, pid, "auth bypass")
    f2 = _seed_fact(http_client, pid, "idor dump")

    r = http_client.post(
        f"/projects/{pid}/attack-paths",
        json={"name": "auth->idor", "fact_chain": [f1, f2], "description": "chain", "severity": "high"},
    )
    assert r.status_code == 201
    ap = r.json()
    assert ap["id"] == "ap001"
    assert ap["fact_chain"] == [f1, f2]
    assert ap["severity"] == "high"

    listed = http_client.get(f"/projects/{pid}/attack-paths").json()
    assert len(listed) == 1 and listed[0]["name"] == "auth->idor"

    # get_project (dashboard data source) must also surface attack paths
    detail = http_client.get(f"/projects/{pid}").json()
    assert len(detail["attack_paths"]) == 1
    assert detail["attack_paths"][0]["fact_chain"] == [f1, f2]

    yaml_text = http_client.get(f"/projects/{pid}/export?format=yaml").text
    assert "attack_paths" in yaml_text and "auth->idor" in yaml_text

    assert http_client.delete(f"/projects/{pid}/attack-paths/{ap['id']}").status_code == 204
    assert http_client.get(f"/projects/{pid}/attack-paths").json() == []


def test_attack_path_rejects_unknown_fact(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    r = http_client.post(
        f"/projects/{pid}/attack-paths",
        json={"name": "bad", "fact_chain": ["f999"], "description": "no such fact"},
    )
    assert r.status_code == 404
