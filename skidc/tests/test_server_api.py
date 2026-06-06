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
