from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from skidc.server import db
from skidc.server.db import get_conn
from skidc.server.services import reconcile_project_coverage
from tests.support.web_assessment import (
    claim_intent,
    conclude_intent,
    coverage_by_id,
    create_intent,
    create_real_web_project,
    create_required_coverage,
    create_surface,
)


def test_explicit_web_test_without_candidate_is_negative_terminal(http_client):
    project_id = create_real_web_project(http_client)
    surface = create_surface(http_client, project_id)
    coverage = create_required_coverage(
        http_client,
        project_id,
        surface,
        family="identity_auth",
        variant="authentication_flow",
    )
    intent = create_intent(
        http_client,
        project_id,
        surface=surface,
        coverage_ids=[coverage["id"]],
    )
    claim_intent(http_client, project_id, intent["id"])
    concluded = conclude_intent(
        http_client,
        project_id,
        intent["id"],
        description="Authentication bypass probes were rejected.",
        data={"tested_surface_refs": [f" {surface['id']} ", surface["id"]]},
    )
    assert concluded["fact"]["data"]["tested_surface_refs"] == [surface["id"]]
    item = coverage_by_id(http_client, project_id, coverage["id"])
    assert item["execution_status"] == "completed"
    assert item["outcome"] == "not_vulnerable"


def _candidate_coverage_with_verify(http_client, *, result: str) -> dict:
    project_id = create_real_web_project(http_client)
    surface = create_surface(http_client, project_id)
    coverage = create_required_coverage(
        http_client,
        project_id,
        surface,
        family="identity_auth",
        variant="authentication_flow",
    )
    explore = create_intent(
        http_client,
        project_id,
        surface=surface,
        coverage_ids=[coverage["id"]],
    )
    claim_intent(http_client, project_id, explore["id"])
    candidate = conclude_intent(
        http_client,
        project_id,
        explore["id"],
        description="Candidate authentication bypass requires independent reproduction.",
        data={
            "tested_surface_refs": [surface["id"]],
            "verify_request": "Reproduce the authentication bypass.",
            "verify_requests": [{
                "claim": "Reproduce the authentication bypass.",
                "surface_refs": [surface["id"]],
                "evidence_refs": [],
            }],
        },
    )["fact"]
    pending = coverage_by_id(http_client, project_id, coverage["id"])
    assert pending["execution_status"] == "testing"
    assert pending["outcome"] is None

    verify = create_intent(
        http_client,
        project_id,
        surface=surface,
        coverage_ids=[coverage["id"]],
        action_kind="verify",
        test_variant="authentication_flow",
        from_ids=[candidate["id"]],
    )
    claim_intent(http_client, project_id, verify["id"], worker="verifier")
    conclude_intent(
        http_client,
        project_id,
        verify["id"],
        worker="verifier",
        description=f"Independent verification result: {result}.",
        status=result,
        verification_of=candidate["id"],
        parent_fact=candidate["id"],
        kind="verification_result",
        data={"result": result, "attempts": []},
        evidence_refs=[f"task_log:verify-{result}"],
        coverage_refs=[coverage["id"]],
    )
    return coverage_by_id(http_client, project_id, coverage["id"])


def test_candidate_coverage_waits_for_every_terminal_verify(http_client):
    completed = _candidate_coverage_with_verify(http_client, result="not_reproduced")
    assert completed["execution_status"] == "completed"
    assert completed["outcome"] == "not_vulnerable"


def test_reproduced_candidate_makes_coverage_vulnerable(http_client):
    completed = _candidate_coverage_with_verify(http_client, result="reproduced")
    assert completed["execution_status"] == "completed"
    assert completed["outcome"] == "vulnerable"

def _claim_web_reason(http: TestClient, project_id: str, worker: str = "reasoner") -> None:
    response = http.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": worker, "trigger": "test completion"},
    )
    assert response.status_code == 200




def test_attack_path_panel_serves_utf8_chinese(http_client: TestClient) -> None:
    response = http_client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "charset=utf-8" in response.headers["content-type"].lower()
    assert "已完成的因果攻击路径" in response.text
    assert "只从已结束的 Fact–Intent 图反向派生" in response.text
    assert "因果 Intent：" in response.text
    assert "宸插畬鎴" not in response.text


def test_frontend_automatically_refreshes_project_state(http_client: TestClient) -> None:
    response = http_client.get("/")
    assert response.status_code == 200
    assert "async function reloadLiveData()" in response.text
    assert "window.setInterval(reloadLiveData, 2000)" in response.text
    assert 'document.addEventListener("visibilitychange", reloadLiveData)' in response.text


def test_create_project_seeds_origin_and_goal(http_client: TestClient) -> None:
    r = http_client.post("/projects", json={"title": "t", "origin": "10.0.0.5", "goal": "root"})
    assert r.status_code == 201
    body = r.json()
    assert body["project"]["status"] == "active"
    assert [f["id"] for f in body["facts"]] == ["origin", "goal"]


def test_project_reads_do_not_require_sqlite_write_lock(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "t", "origin": "o", "goal": "g"},
    ).json()["project"]["id"]
    writer = sqlite3.connect(db._db_path, timeout=0.1)
    writer.execute("BEGIN IMMEDIATE")
    try:
        assert http_client.get("/projects").status_code == 200
        assert http_client.get(f"/projects/{pid}").status_code == 200
    finally:
        writer.rollback()
        writer.close()


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


def test_complete_blocks_when_open_intents_remain(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    http_client.post(
        f"/projects/{pid}/intents",
        json={"from": ["origin"], "description": "still needs testing", "creator": "r"},
    )

    r = http_client.post(f"/projects/{pid}/complete", json={"from": ["origin"], "description": "done", "worker": "w1"})

    assert r.status_code == 409
    assert "Fact-Intent graph work" in r.text
    assert "i001:intent status=open" in r.text
    payload = r.json()["detail"]
    assert payload["code"] == "completion_blocked"
    assert payload["blockers"][0]["kind"] == "intent"
    assert payload["blockers"][0]["ref"] == "i001"
    assert http_client.get(f"/projects/{pid}").json()["project"]["status"] == "active"


def test_complete_allows_terminal_failed_result_fact(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    iid = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "verify possible RCE",
            "creator": "r",
            "priority": 10,
            "action_kind": "rce_probe",
        },
    ).json()["id"]
    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "RCE verification attempt.",
            "test_family": "file_path",
            "intent_id": iid,
            "priority": 10,
        },
    ).json()
    failed = http_client.post(
        f"/projects/{pid}/intents/{iid}/failure",
        json={"worker": "w1", "error": "timeout", "max_attempts": 1, "backoff_seconds": 0},
    )
    assert failed.json()["status"] == "concluded"
    assert failed.json()["to"] is not None

    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={"from": ["origin"], "description": "done with the failed attempt recorded", "worker": "w1"},
    )

    assert completed.status_code == 200
    detail = http_client.get(f"/projects/{pid}").json()
    assert detail["project"]["status"] == "completed"
    failed_intent = next(item for item in detail["intents"] if item["id"] == iid)
    assert failed_intent["status"] == "concluded"
    assert next(fact for fact in detail["facts"] if fact["id"] == failed_intent["to"])["status"] is None
    result = next(item for item in detail["coverage_items"] if item["id"] == coverage["id"])
    assert result["status"] == "inconclusive"
    assert result["execution_status"] == "completed"
    assert result["outcome"] == "inconclusive"


def test_coverage_item_create_update_and_project_detail(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    iid = http_client.post(
        f"/projects/{pid}/intents",
        json={"from": ["origin"], "description": "test login form", "creator": "r"},
    ).json()["id"]

    r = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "form",
            "target": "al.xhcms",
            "port": 80,
            "method": "POST",
            "path": "/xhcms/admin.php",
            "description": "Admin login form should be checked for auth bypass and default credentials.",
            "priority": 9,
            "source_fact_id": "origin",
            "intent_id": iid,
        },
    )

    assert r.status_code == 201
    item = r.json()
    assert item["id"] == "cov001"
    assert item["status"] == "untested"
    assert item["intent_id"] == iid
    assert item["intent_ids"] == [iid]

    updated = http_client.put(
        f"/projects/{pid}/coverage/{item['id']}",
        json={"status": "not_vulnerable", "evidence_ref": "POST login tested with default pairs"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "not_vulnerable"

    listed = http_client.get(f"/projects/{pid}/coverage").json()
    assert len(listed) == 1
    assert listed[0]["evidence_ref"] == "POST login tested with default pairs"

    detail = http_client.get(f"/projects/{pid}").json()
    assert detail["coverage_items"][0]["id"] == "cov001"


def test_intent_conclude_reconciles_multiple_coverage_items(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    coverage_ids = []
    for description, item_type in (
        ("Admin login authentication bypass", "admin_route"),
        ("Admin login SQL injection", "param"),
    ):
        response = http_client.post(
            f"/projects/{pid}/coverage",
            json={
                "item_type": item_type,
                "path": "/admin/login.php",
                "description": description,
                "priority": 9,
            },
        )
        assert response.status_code == 201
        coverage_ids.append(response.json()["id"])

    intent_response = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "verify admin login",
            "creator": "reasoner",
            "coverage_refs": coverage_ids,
        },
    )
    assert intent_response.status_code == 201
    intent_id = intent_response.json()["id"]
    assert intent_response.json()["coverage_refs"] == coverage_ids

    assert http_client.post(
        f"/projects/{pid}/intents/{intent_id}/heartbeat",
        json={"worker": "w1"},
    ).status_code == 200
    concluded = http_client.post(
        f"/projects/{pid}/intents/{intent_id}/conclude",
        json={
            "worker": "w1",
            "description": "Admin login SQL injection and authentication bypass confirmed.",
            "status": "confirmed",
            "severity": "critical",
            "vuln_type": "sqli_auth_bypass",
        },
    )

    assert concluded.status_code == 200
    fact = concluded.json()["fact"]
    assert fact["coverage_refs"] == coverage_ids
    listed = http_client.get(f"/projects/{pid}/coverage").json()
    assert {item["status"] for item in listed} == {"confirmed"}
    assert all(item["intent_ids"] == [intent_id] for item in listed)
    assert all(item["evidence_fact_ids"] == [fact["id"]] for item in listed)


def test_intent_conclude_without_structured_status_is_inconclusive(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "admin_route",
            "path": "/admin/login.php",
            "description": "Admin login authentication bypass",
            "priority": 9,
        },
    ).json()
    intent_response = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "verify admin login",
            "creator": "w1",
            "worker": "w1",
            "coverage_refs": [coverage["id"]],
        },
    )
    assert intent_response.status_code == 201
    intent = intent_response.json()

    concluded = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={"worker": "w1", "description": "Admin login request completed without a structured verdict."},
    )

    assert concluded.status_code == 200
    item = http_client.get(f"/projects/{pid}/coverage").json()[0]
    assert item["status"] == "inconclusive"
    fact_id = concluded.json()["fact"]["id"]
    assert item["evidence_fact_ids"] == [fact_id]

    verified = http_client.put(
        f"/projects/{pid}/facts/{fact_id}",
        json={"status": "confirmed", "recon_evidence_ref": "login response evidence"},
    )
    assert verified.status_code == 200
    assert http_client.get(f"/projects/{pid}/coverage").json()[0]["status"] == "confirmed"

    failed = http_client.put(
        f"/projects/{pid}/facts/{fact_id}",
        json={"status": "failed", "recon_evidence_ref": "verification method stopped producing evidence"},
    )
    assert failed.status_code == 200
    assert http_client.get(f"/projects/{pid}/coverage").json()[0]["status"] == "inconclusive"

    refuted = http_client.put(
        f"/projects/{pid}/facts/{fact_id}",
        json={"status": "refuted", "recon_evidence_ref": "retest disproved bypass"},
    )
    assert refuted.status_code == 200
    assert http_client.get(f"/projects/{pid}/coverage").json()[0]["status"] == "not_vulnerable"


def test_coverage_creation_does_not_text_match_existing_terminal_fact(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    open_fact = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "Investigating /admin/login.php on al.xhcms.",
            "recon_target": "al.xhcms",
        },
    )
    assert open_fact.status_code == 201
    fact = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "Admin login authentication bypass verified on al.xhcms.",
            "status": "confirmed",
            "severity": "high",
            "vuln_type": "auth_bypass",
            "recon_target": "al.xhcms",
        },
    )
    assert fact.status_code == 201

    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "service",
            "target": "al.xhcms",
            "port": 80,
            "description": "Admin login panel",
            "priority": 8,
        },
    )

    assert coverage.status_code == 201
    item = coverage.json()
    assert item["status"] == "untested"
    assert item["evidence_ref"] is None
    assert item["evidence_fact_ids"] == []

    first_reconcile = http_client.post(f"/projects/{pid}/coverage/reconcile")
    second_reconcile = http_client.post(f"/projects/{pid}/coverage/reconcile")
    assert first_reconcile.status_code == 200
    assert second_reconcile.status_code == 200
    assert first_reconcile.json()[0] == second_reconcile.json()[0]
    assert second_reconcile.json()[0]["evidence_fact_ids"] == []


def test_surface_inventory_upsert_and_profile_coverage_fields(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "web", "origin": "https://example.test/", "goal": "assess", "mode": "real_website"},
    ).json()["project"]["id"]
    surface_payload = {
        "fingerprint": "surface-login-1",
        "surface_group": "auth:/admin/login.php",
        "target": "example.test",
        "port": 443,
        "method": "POST",
        "path_template": "/admin/login.php",
        "params": ["password", "username"],
        "surface_type": "form",
        "auth_context": "anonymous",
        "roles": ["admin"],
        "traits": {"auth": True, "has_input": True, "writes": True},
    }
    first = http_client.post(f"/projects/{pid}/surfaces", json=surface_payload)
    second = http_client.post(f"/projects/{pid}/surfaces", json={**surface_payload, "roles": ["admin", "operator"]})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["roles"] == ["admin", "operator"]

    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
                "description": "auth:/admin/login.php x identity_auth (anonymous)",
                "surface_group": "auth:/admin/login.php",
                "surface_fingerprint": surface_payload["fingerprint"],
            "test_family": "identity_auth",
            "test_variants": ["default_credentials", "auth_bypass"],
            "auth_context": "anonymous",
            "roles": ["admin"],
            "applicability_reason": "Login surface implements authentication behavior.",
            "required": True,
            "standard_refs": ["WSTG-v4.2-ATHN"],
            "priority": 8,
            "execution_status": "untested",
        },
    )
    assert coverage.status_code == 201
    item = coverage.json()
    assert item["test_family"] == "identity_auth"
    assert item["test_variants"] == ["default_credentials", "auth_bypass"]
    assert item["execution_status"] == "untested"
    assert item["outcome"] is None

    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "Test the admin authentication surface.",
            "creator": "reasoner",
            "coverage_refs": [item["id"]],
            "test_variant": "auth_bypass",
            "action_kind": "security_test",
            "surface_ref": first.json()["id"],
        },
    )
    assert intent.status_code == 201
    intent_id = intent.json()["id"]
    assert http_client.get(f"/projects/{pid}/coverage").json()[0]["execution_status"] == "queued"
    assert http_client.post(
        f"/projects/{pid}/intents/{intent_id}/heartbeat",
        json={"worker": "w1"},
    ).status_code == 200
    assert http_client.get(f"/projects/{pid}/coverage").json()[0]["execution_status"] == "testing"
    resolved = http_client.post(
        f"/projects/{pid}/intents/{intent_id}/conclude",
        json={
            "worker": "w1",
            "description": "Authentication checks completed without a bypass.",
            "status": "not_vulnerable",
            "vuln_type": "auth_bypass",
            "data": {"tested_surface_refs": [first.json()["id"]]},
        },
    )
    assert resolved.status_code == 200
    resolved_item = http_client.get(f"/projects/{pid}/coverage").json()[0]
    assert resolved_item["status"] == "untested"
    variants = {result["variant"]: result for result in resolved_item["variant_results"]}
    assert variants["auth_bypass"]["status"] == "not_vulnerable"
    assert variants["default_credentials"]["status"] == "untested"
    assert resolved_item["execution_status"] == "untested"
    assert resolved_item["outcome"] is None

    detail = http_client.get(f"/projects/{pid}").json()
    assert len(detail["surface_inventory"]) == 1
    assert detail["coverage_items"][0]["standard_refs"] == ["WSTG-v4.2-ATHN"]


def test_surface_test_status_completes_on_terminal_negative_coverage(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={
            "title": "surface negative closure",
            "origin": "https://example.test/",
            "goal": "assess",
            "mode": "real_website",
        },
    ).json()["project"]["id"]
    fingerprint = "search-surface"
    surface = http_client.post(
        f"/projects/{pid}/surfaces",
        json={
            "fingerprint": fingerprint,
            "surface_group": "web:/search",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/search",
            "params": ["q"],
            "surface_type": "route",
            "auth_context": "anonymous",
            "planning_status": "assessed",
            "source_fact_id": "origin",
        },
    )
    assert surface.status_code == 200
    assert surface.json()["test_status"] == "not_applicable"

    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "Test SQL injection on the observed search behavior.",
            "surface_group": "web:/search",
            "surface_fingerprint": fingerprint,
            "test_family": "injection",
            "test_variants": ["sql"],
            "required": True,
            "priority": 8,
        },
    )
    assert coverage.status_code == 201
    coverage_id = coverage.json()["id"]
    before = http_client.get(f"/projects/{pid}/surfaces").json()[0]
    assert before["test_status"] == "untested"
    assert before["required_coverage_count"] == 1
    assert before["completed_coverage_count"] == 0

    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "Run concrete negative SQL injection probes.",
            "creator": "reasoner",
            "test_variant": "sql",
            "action_kind": "security_test",
            "surface_ref": surface.json()["id"],
            "coverage_refs": [coverage_id],
        },
    ).json()
    assert http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/heartbeat",
        json={"worker": "executor"},
    ).status_code == 200
    during = http_client.get(f"/projects/{pid}/surfaces").json()[0]
    assert during["test_status"] == "testing"

    concluded = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={
            "worker": "executor",
            "description": "Boolean, error, and time probes were negative.",
            "status": "not_vulnerable",
            "vuln_type": "sql",
            "coverage_refs": [coverage_id],
            "data": {"tested_surface_refs": [surface.json()["id"]]},
        },
    )
    assert concluded.status_code == 200
    after = http_client.get(f"/projects/{pid}/surfaces").json()[0]
    assert after["test_status"] == "completed"
    assert after["required_coverage_count"] == 1
    assert after["completed_coverage_count"] == 1


def test_non_required_support_service_does_not_block_completion(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "web", "origin": "https://example.test/", "goal": "assess", "mode": "real_website", "recon_profile": {"required_categories": []}},
    ).json()["project"]["id"]
    assert http_client.put(f"/projects/{pid}/phase", json={"phase": "explore"}).status_code == 200
    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "service",
            "target": "example.test",
            "port": 3306,
            "description": "support:example.test:3306 x support_service (anonymous)",
            "surface_group": "support:example.test:3306",
            "test_family": "support_service",
            "required": False,
            "priority": 10,
        },
    )
    assert coverage.status_code == 201

    _claim_web_reason(http_client, pid)
    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={"from": [], "description": "Required Web coverage is complete.", "worker": "reasoner"},
    )
    assert completed.status_code == 200


def test_complete_allows_unresolved_coverage_as_report_limitation(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "upload_point",
            "path": "/xhcms/upload.php",
            "description": "Upload endpoint needs verification.",
            "status": "inconclusive",
            "priority": 10,
        },
    )

    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={"from": ["origin"], "description": "done with an explicit limitation", "worker": "w1"},
    )

    assert completed.status_code == 200
    detail = http_client.get(f"/projects/{pid}").json()
    assert detail["project"]["status"] == "completed"
    assert detail["project"]["completion_blockers"] == []
    assert detail["coverage_items"][0]["status"] == "inconclusive"


def test_complete_allows_low_priority_unresolved_coverage(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "route",
            "path": "/xhcms/static/logo.png",
            "description": "Low-value static asset note.",
            "status": "untested",
            "priority": 4,
        },
    )

    r = http_client.post(f"/projects/{pid}/complete", json={"from": ["origin"], "description": "done", "worker": "w1"})

    assert r.status_code == 200
    assert http_client.get(f"/projects/{pid}").json()["project"]["status"] == "completed"


def test_complete_allows_resolved_completion_priority_coverage(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    item = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "param",
            "path": "/xhcms/index.php",
            "param": "id",
            "description": "SQLi check for id parameter.",
            "status": "untested",
            "priority": 10,
        },
    ).json()
    http_client.put(
        f"/projects/{pid}/coverage/{item['id']}",
        json={"status": "not_vulnerable", "evidence_ref": "boolean and time probes were negative"},
    )

    r = http_client.post(f"/projects/{pid}/complete", json={"from": ["origin"], "description": "done", "worker": "w1"})

    assert r.status_code == 200
    assert http_client.get(f"/projects/{pid}").json()["project"]["status"] == "completed"


def test_complete_allows_pending_critical_fact_as_unconfirmed_result(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    fact = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "RCE appears possible through the upload endpoint.",
            "vuln_type": "rce",
            "severity": "critical",
            "status": "pending",
        },
    ).json()

    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={"from": [fact["id"]], "description": "RCE remains unconfirmed", "worker": "w1"},
    )

    assert completed.status_code == 200
    assert http_client.get(f"/projects/{pid}").json()["project"]["status"] == "completed"


def test_confirmed_critical_fact_does_not_prevent_finite_completion(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    fact = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "Upload endpoint allows PHP execution.",
            "vuln_type": "rce",
            "severity": "critical",
            "status": "confirmed",
            "recon_evidence_ref": "harmless marker response",
        },
    ).json()

    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={"from": [fact["id"]], "description": "confirmed result reported", "worker": "w1"},
    )

    assert completed.status_code == 200
    assert http_client.get(f"/projects/{pid}").json()["project"]["status"] == "completed"


def test_complete_allows_verified_high_risk_findings(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    fact = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "SQL injection confirmed with boolean and time-based checks.",
            "vuln_type": "sqli",
            "severity": "high",
            "status": "confirmed",
        },
    ).json()
    verification = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "A second technique independently reproduced the SQL injection.",
            "vuln_type": "sqli",
            "severity": "high",
            "status": "verified",
            "verification_of": fact["id"],
        },
    ).json()

    r = http_client.post(
        f"/projects/{pid}/complete",
        json={"from": [fact["id"], verification["id"]], "description": "done", "worker": "w1"},
    )

    assert r.status_code == 200
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


def test_task_logs_capture_input_and_report_includes_evidence(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={
            "title": "real site",
            "origin": "http://al.xhcms/xhcms/",
            "goal": "assess authorized test site",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "scope_policy": {
                "allowed_targets": ["al.xhcms"],
                "blocked_targets": [],
                "allowed_ports": [80],
                "blocked_ports": [],
                "passive_only": False,
            },
        },
    ).json()["project"]["id"]
    iid = http_client.post(
        f"/projects/{pid}/intents",
        json={"from": ["origin"], "description": "probe upload surface", "creator": "r", "worker": None},
    ).json()["id"]
    http_client.post(f"/projects/{pid}/intents/{iid}/heartbeat", json={"worker": "w1"})
    fact = http_client.post(
        f"/projects/{pid}/intents/{iid}/conclude",
        json={
            "worker": "w1",
            "description": "Upload endpoint accepts executable PHP files.",
            "scope": "http://al.xhcms/xhcms/",
                "vuln_type": "unrestricted_upload",
                "severity": "high",
                "status": "confirmed",
                "recon_evidence_ref": "POST /upload.php returned 200",
        },
    ).json()["fact"]
    http_client.post(
        f"/projects/{pid}/attack-paths",
        json={
            "name": "upload php",
            "fact_chain": ["origin", fact["id"]],
            "description": "Upload a PHP payload and request it from the web root.",
            "severity": "high",
        },
    )
    http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "upload_point",
            "target": "al.xhcms",
            "port": 80,
            "path": "/xhcms/upload.php",
            "description": "Upload endpoint covered by executable upload verification.",
            "status": "confirmed",
            "priority": 9,
            "evidence_ref": "POST /upload.php returned 200",
            "source_fact_id": fact["id"],
            "intent_id": iid,
        },
    )
    log = http_client.post(
        f"/projects/{pid}/logs",
        json={
            "task_type": "explore",
            "intent_id": iid,
            "worker_name": "w1",
            "phase": "explore_execute",
            "stdin": "argv:\nskidc-worker --prompt ...\n\nprompt:\nCheck upload endpoint",
            "stdout": "confirmed upload behavior",
            "stderr": "",
            "return_code": 0,
            "duration_ms": 123,
        },
    ).json()

    listed = http_client.get(f"/projects/{pid}/logs").json()
    assert listed[0]["stdin_preview"].startswith("argv:")
    detail = http_client.get(f"/projects/{pid}/logs/{log['id']}").json()
    assert "Check upload endpoint" in detail["stdin"]

    report = http_client.get(f"/projects/{pid}/export?format=report").text
    assert "# Penetration Test Report: real site" in report
    assert "## Test Process" in report
    assert "## Test Results" in report
    assert "## Coverage Ledger" in report
    assert "Independently reproduced security findings: 0" in report
    assert "confirmed: 1" not in report
    assert "Coverage, Surface, and Hypothesis records are audit context" in report
    assert "## Completed Causal Attack Paths" in report
    assert "Upload endpoint accepts executable PHP files." in report
    assert "Input:" in report and "Check upload endpoint" in report

    yaml_text = http_client.get(f"/projects/{pid}/export?format=yaml").text
    assert "coverage_items" in yaml_text
    assert "Upload endpoint covered by executable upload verification." in yaml_text


def test_report_separates_support_services_and_limited_findings_with_log_trace(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={
            "title": "classified report",
            "origin": "http://al.xhcms/xhcms/",
            "goal": "assess the authorized web application",
            "mode": "real_website",
            "recon_profile": {"required_categories": []},
            "scope_policy": {
                "allowed_targets": ["al.xhcms"],
                "allowed_ports": [80, 3306],
                "support_ports": [3306],
            },
        },
    ).json()["project"]["id"]

    assert http_client.put(f"/projects/{pid}/phase", json={"phase": "explore"}).status_code == 200
    support_coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "service",
            "target": "al.xhcms",
            "port": 3306,
            "description": "Optional MySQL exposure and credential check.",
            "test_family": "support_service",
            "surface_group": "support:mysql:3306",
            "priority": 3,
            "required": False,
        },
    ).json()
    support_intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "verify explicitly allowed MySQL service",
            "creator": "reasoner",
            "coverage_refs": [support_coverage["id"]],
        },
    ).json()
    http_client.post(
        f"/projects/{pid}/intents/{support_intent['id']}/heartbeat",
        json={"worker": "w1"},
    )
    support_fact = http_client.post(
        f"/projects/{pid}/intents/{support_intent['id']}/conclude",
        json={
            "worker": "w1",
            "description": "MySQL 3306 accepts a weak test credential.",
            "scope": "al.xhcms:3306",
            "vuln_type": "weak_credentials",
            "severity": "high",
            "status": "confirmed",
            "coverage_refs": [support_coverage["id"]],
        },
    ).json()["fact"]
    support_log = http_client.post(
        f"/projects/{pid}/logs",
        json={
            "task_type": "explore",
            "intent_id": support_intent["id"],
            "worker_name": "w1",
            "phase": "explore_execute",
            "stdin": "verify support service al.xhcms:3306",
            "stdout": "credential accepted",
            "stderr": "",
            "return_code": 0,
            "duration_ms": 80,
        },
    ).json()

    ssrf_coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "route",
            "target": "al.xhcms",
            "port": 80,
            "path": "/xhcms/fetch.php",
            "description": "Check server-side URL fetch restrictions.",
            "test_family": "server_side_processing",
            "surface_group": "route:GET:/xhcms/fetch.php",
            "test_variants": ["ssrf"],
            "priority": 7,
        },
    ).json()
    ssrf_intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "verify possible SSRF with safe callbacks",
            "creator": "reasoner",
            "coverage_refs": [ssrf_coverage["id"]],
            "test_variant": "ssrf",
        },
    ).json()
    http_client.post(
        f"/projects/{pid}/intents/{ssrf_intent['id']}/heartbeat",
        json={"worker": "w2"},
    )
    ssrf_fact = http_client.post(
        f"/projects/{pid}/intents/{ssrf_intent['id']}/conclude",
        json={
            "worker": "w2",
            "description": "SSRF behavior could not be confirmed because callbacks were blocked.",
            "scope": "http://al.xhcms/xhcms/fetch.php",
            "vuln_type": "ssrf",
            "severity": "high",
            "status": "inconclusive",
            "coverage_refs": [ssrf_coverage["id"]],
        },
    ).json()["fact"]
    ssrf_log = http_client.post(
        f"/projects/{pid}/logs",
        json={
            "task_type": "explore",
            "intent_id": ssrf_intent["id"],
            "worker_name": "w2",
            "phase": "explore_execute",
            "stdin": "send safe callback probes",
            "stdout": "",
            "stderr": "callback unavailable",
            "return_code": 1,
            "duration_ms": 100,
        },
    ).json()

    waived = http_client.post(
        f"/projects/{pid}/coverage/{ssrf_coverage['id']}/exclude",
        json={"reason": "callback infrastructure is unavailable in this engagement", "creator": "human"},
    )
    assert waived.status_code == 200

    _claim_web_reason(http_client, pid)
    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={
            "from": [],
            "description": "finish with the inconclusive SSRF attempt recorded as a limitation",
            "worker": "reasoner",
        },
    )
    assert completed.status_code == 200

    detail = http_client.get(f"/projects/{pid}").json()
    assert detail["project"]["run_state"] == "completed"
    facts = {fact["id"]: fact for fact in detail["facts"]}
    assert facts[support_fact["id"]]["surface_class"] is None
    assert facts[support_fact["id"]]["result_class"] is None
    assert support_log["id"] in facts[support_fact["id"]]["task_log_refs"]
    assert facts[ssrf_fact["id"]]["surface_class"] is None
    assert facts[ssrf_fact["id"]]["result_class"] is None
    assert detail["project"]["completion_blockers"] == []

    report = http_client.get(f"/projects/{pid}/export?format=report").text
    assert "MySQL 3306 accepts a weak test credential." in report
    assert "SSRF behavior could not be confirmed" in report
    assert "Independently reproduced security findings: 0" in report

    yaml_text = http_client.get(f"/projects/{pid}/export?format=yaml").text
    assert "result_class: confirmed" not in yaml_text
    assert support_log["id"] in yaml_text


def test_confirmed_security_intent_is_not_downgraded_by_inconclusive_coverage(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "status precedence", "origin": "http://example.test/", "goal": "assess", "mode": "real_website"},
    ).json()["project"]["id"]
    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "SQL injection verification",
            "surface_group": "web:/content",
            "test_family": "injection",
            "priority": 7,
        },
    ).json()
    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "verify SQL injection",
            "creator": "reasoner",
            "action_kind": "sql_injection",
            "coverage_refs": [coverage["id"]],
        },
    ).json()
    http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/heartbeat",
        json={"worker": "worker"},
    )
    fact = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={
            "worker": "worker",
            "description": "Error-based SQL injection extracted a harmless database marker.",
            "status": "confirmed",
        },
    ).json()["fact"]
    http_client.put(
        f"/projects/{pid}/coverage/{coverage['id']}",
        json={"execution_status": "completed", "outcome": "inconclusive"},
    )
    recon_intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "inventory static assets",
            "creator": "reasoner",
            "action_kind": "asset_discovery",
        },
    ).json()
    http_client.post(
        f"/projects/{pid}/intents/{recon_intent['id']}/heartbeat",
        json={"worker": "worker"},
    )
    recon_fact = http_client.post(
        f"/projects/{pid}/intents/{recon_intent['id']}/conclude",
        json={"worker": "worker", "description": "Static asset inventory completed.", "status": "confirmed"},
    ).json()["fact"]

    detail = http_client.get(f"/projects/{pid}").json()
    facts = {item["id"]: item for item in detail["facts"]}

    assert facts[fact["id"]]["result_class"] is None
    assert facts[recon_fact["id"]]["result_class"] is None
    assert detail["attack_paths"] == []

    report = http_client.get(f"/projects/{pid}/export?format=report").text
    assert "Error-based SQL injection extracted" in report
    assert "Static asset inventory completed." in report


def test_recon_completion_is_informational_and_http_tls_coverage_is_not_applicable(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "lean coverage", "origin": "http://example.test/", "goal": "assess", "mode": "real_website", "recon_profile": {"required_categories": []}},
    ).json()["project"]["id"]
    recon_coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "target": "example.test",
            "port": 80,
            "description": "Discovered Web surface requires configuration and exposure review.",
            "surface_group": "web:example.test:80",
            "test_family": "surface_config",
            "priority": 5,
        },
    ).json()
    tls_coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "target": "example.test",
            "port": 80,
            "description": "HTTP transport check",
            "surface_group": "transport:example.test:80",
            "test_family": "crypto_transport",
            "priority": 5,
        },
    ).json()
    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "enumerate public routes",
            "creator": "reasoner",
            "action_kind": "route_discovery",
            "coverage_refs": [recon_coverage["id"]],
        },
    ).json()
    http_client.post(f"/projects/{pid}/intents/{intent['id']}/heartbeat", json={"worker": "worker"})
    fact = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={"worker": "worker", "description": "Public route inventory completed.", "status": "confirmed"},
    ).json()["fact"]

    assert http_client.put(f"/projects/{pid}/phase", json={"phase": "explore"}).status_code == 200
    detail = http_client.get(f"/projects/{pid}").json()
    coverage = {item["id"]: item for item in detail["coverage_items"]}
    facts = {item["id"]: item for item in detail["facts"]}
    assert coverage[recon_coverage["id"]]["execution_status"] == "completed"
    assert coverage[recon_coverage["id"]]["outcome"] == "informational"
    assert coverage[tls_coverage["id"]]["outcome"] == "not_applicable"
    assert coverage[tls_coverage["id"]]["required"] is False
    assert facts[fact["id"]]["result_class"] is None

    _claim_web_reason(http_client, pid)
    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={"from": [], "description": "assessment complete", "worker": "reasoner"},
    )
    assert completed.status_code == 200


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


def _seed_fact(http_client: TestClient, pid: str, description: str, status: str | None = None) -> str:
    iid = http_client.post(
        f"/projects/{pid}/intents",
        json={"from": ["origin"], "description": "probe", "creator": "r", "worker": None},
    ).json()["id"]
    http_client.post(f"/projects/{pid}/intents/{iid}/heartbeat", json={"worker": "w1"})
    return http_client.post(
        f"/projects/{pid}/intents/{iid}/conclude",
        json={"worker": "w1", "description": description, "status": status},
    ).json()["fact"]["id"]


def _complete_confirmed_attack_chain(http_client: TestClient) -> tuple[str, str]:
    pid = http_client.post(
        "/projects",
        json={"title": "derived path", "origin": "o", "goal": "g"},
    ).json()["project"]["id"]
    first_fact = _seed_fact(http_client, pid, "authentication boundary reached", "confirmed")
    second_intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": [first_fact],
            "description": "verify object authorization impact",
            "creator": "reasoner",
            "action_kind": "authorization_probe",
        },
    ).json()
    http_client.post(
        f"/projects/{pid}/intents/{second_intent['id']}/heartbeat",
        json={"worker": "w1"},
    )
    terminal_fact = http_client.post(
        f"/projects/{pid}/intents/{second_intent['id']}/conclude",
        json={
            "worker": "w1",
            "description": "Confirmed unauthorized access to another user's object.",
            "status": "confirmed",
            "vuln_type": "IDOR",
            "severity": "high",
        },
    ).json()["fact"]["id"]
    assert http_client.get(f"/projects/{pid}/attack-paths").json() == []
    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={
            "from": [terminal_fact],
            "description": "Verified finding is connected to the assessment goal.",
            "worker": "reasoner",
        },
    )
    assert completed.status_code == 200
    return pid, terminal_fact


def test_attack_paths_are_read_only_goal_derived_and_disappear_on_reopen(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "no manual paths", "origin": "o", "goal": "g"},
    ).json()["project"]["id"]
    blocked_write = http_client.post(
        f"/projects/{pid}/attack-paths",
        json={
            "name": "invented chain",
            "fact_chain": ["origin"],
            "description": "must not be writable",
        },
    )
    assert blocked_write.status_code == 409
    assert blocked_write.json()["detail"]["code"] == "attack_paths_read_only"

    pid, terminal_fact = _complete_confirmed_attack_chain(http_client)
    paths = http_client.get(f"/projects/{pid}/attack-paths").json()
    assert len(paths) == 1
    path = paths[0]
    assert path["derived_from_goal"] is True
    assert path["fact_chain"][-2:] == [terminal_fact, "goal"]
    assert path["status"] == "complete"
    assert len(path["intent_refs"]) == 3
    assert path["intent_refs"][-1].startswith("i")
    assert http_client.get(f"/projects/{pid}").json()["attack_paths"] == paths
    yaml_text = http_client.get(f"/projects/{pid}/export?format=yaml").text
    assert "derived_from_goal: true" in yaml_text

    reopened = http_client.post(
        f"/projects/{pid}/reopen",
        json={"description": "new external feedback", "creator": "human"},
    )
    assert reopened.status_code == 200
    assert http_client.get(f"/projects/{pid}/attack-paths").json() == []

def test_attack_path_rejects_unknown_fact(http_client: TestClient) -> None:
    pid = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g"}).json()["project"]["id"]
    r = http_client.post(
        f"/projects/{pid}/attack-paths",
        json={"name": "bad", "fact_chain": ["f999"], "description": "no such fact"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "attack_paths_read_only"


def test_report_contains_only_completed_goal_derived_attack_paths(
    http_client: TestClient,
) -> None:
    pid, terminal_fact = _complete_confirmed_attack_chain(http_client)
    report = http_client.get(f"/projects/{pid}/export?format=report").text

    assert "## PoC And Evidence" in report
    assert "Completed causal attack paths: 1" in report
    assert terminal_fact in report
    assert "## Hypothesized Attack Paths" not in report
    assert "## Refuted Attack Paths" not in report
    assert "## Inconclusive Attack Paths" not in report


def test_real_website_completion_rejects_direct_or_pending_fact_sources(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={
            "title": "completion integrity",
            "origin": "https://example.test/",
            "goal": "assess",
            "mode": "real_website",
            "recon_profile": {"required_categories": []},
        },
    ).json()["project"]["id"]
    assert http_client.post(f"/projects/{pid}/phase/advance", json={}).status_code == 200
    direct = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "direct unowned claim",
            "status": "confirmed",
            "vuln_type": "xss",
            "severity": "high",
        },
    ).json()
    rejected = http_client.post(
        f"/projects/{pid}/complete",
        json={"from": [direct["id"]], "description": "invalid", "worker": "reasoner"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "invalid_completion_source"

    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "verify reflected output",
            "creator": "reasoner",
            "action_kind": "client_side_probe",
        },
    ).json()
    http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/heartbeat",
        json={"worker": "w1"},
    )
    produced = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={
            "worker": "w1",
            "description": "Controlled reflected output was reproduced.",
            "status": "confirmed",
            "vuln_type": "xss",
            "severity": "high",
        },
    ).json()["fact"]
    verify_intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": [produced["id"]],
            "description": "independently reproduce reflected output",
            "creator": "reasoner",
            "action_kind": "verify_candidate",
        },
    ).json()
    assert http_client.post(
        f"/projects/{pid}/intents/{verify_intent['id']}/heartbeat",
        json={"worker": "verifier"},
    ).status_code == 200
    verification = http_client.post(
        f"/projects/{pid}/intents/{verify_intent['id']}/conclude",
        json={
            "worker": "verifier",
            "description": "A fresh session reproduced controlled reflected output.",
            "status": "reproduced",
            "verification_of": produced["id"],
            "kind": "verification_result",
            "data": {"result": "reproduced", "attempts": [{"attempt": 1}]},
        },
    )
    assert verification.status_code == 200
    verification_fact = verification.json()["fact"]
    _claim_web_reason(http_client, pid)

    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={
            "from": [verification_fact["id"]],
            "description": "concluded evidence assesses the goal",
            "worker": "reasoner",
        },
    )
    assert completed.status_code == 200
    assert len(http_client.get(f"/projects/{pid}/attack-paths").json()) == 1

def test_real_website_intent_requires_one_declared_variant(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "atomic", "origin": "https://example.test/", "goal": "g", "mode": "real_website"},
    ).json()["project"]["id"]
    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "admin_route",
            "path": "/admin/login",
            "description": "Admin authentication checks",
            "test_family": "identity_auth",
            "test_variants": ["default_credentials", "auth_bypass"],
            "priority": 9,
        },
    ).json()
    base = {
        "from": ["origin"],
        "description": "Verify one authentication bypass hypothesis",
        "creator": "w1",
        "worker": "w1",
        "coverage_refs": [coverage["id"]],
    }

    missing = http_client.post(f"/projects/{pid}/intents", json=base)
    assert missing.status_code == 422

    created = http_client.post(
        f"/projects/{pid}/intents",
        json={**base, "test_variant": "auth_bypass"},
    )
    assert created.status_code == 201
    intent = created.json()
    assert intent["test_variant"] == "auth_bypass"
    assert intent["coverage_refs"] == [coverage["id"]]

    concluded = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={
            "worker": "w1",
            "description": "The controlled authentication bypass was reproduced.",
            "status": "confirmed",
            "severity": "high",
            "coverage_refs": [coverage["id"]],
        },
    )
    assert concluded.status_code == 200
    assert concluded.json()["fact"]["vuln_type"] is None

    repeated = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={"worker": "w1", "description": "second fact"},
    )
    assert repeated.status_code == 409
    yaml_text = http_client.get(f"/projects/{pid}/export?format=yaml").text
    assert "test_variant: auth_bypass" in yaml_text
    assert "vuln_type: auth_bypass" not in yaml_text



def test_intent_rejects_fact_for_a_different_variant(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "atomic", "origin": "https://example.test/", "goal": "g", "mode": "real_website"},
    ).json()["project"]["id"]
    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "param",
            "path": "/search",
            "param": "q",
            "description": "Search injection",
            "test_family": "injection",
            "test_variants": ["sql"],
            "priority": 7,
        },
    ).json()
    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "Verify SQL injection in q",
            "creator": "w1",
            "worker": "w1",
            "coverage_refs": [coverage["id"]],
            "test_variant": "sql",
        },
    ).json()

    response = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={
            "worker": "w1",
            "description": "A different mechanism was observed.",
            "status": "confirmed",
            "vuln_type": "command",
        },
    )
    assert response.status_code == 200
    detail = http_client.get(f"/projects/{pid}").json()
    assert next(item for item in detail["intents"] if item["id"] == intent["id"])["to"] is not None


def test_real_website_conclude_cannot_rebind_coverage(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "atomic", "origin": "https://example.test/", "goal": "g", "mode": "real_website"},
    ).json()["project"]["id"]
    bound = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "param",
            "path": "/search",
            "param": "q",
            "description": "Search SQL injection",
            "test_family": "injection",
            "test_variants": ["sql"],
            "priority": 7,
        },
    ).json()
    other = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "param",
            "path": "/run",
            "param": "cmd",
            "description": "Command injection",
            "test_family": "injection",
            "test_variants": ["command"],
            "priority": 7,
        },
    ).json()
    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "Verify SQL injection in q",
            "creator": "w1",
            "worker": "w1",
            "coverage_refs": [bound["id"]],
            "test_variant": "SQL",
        },
    ).json()
    assert intent["test_variant"] == "sql"

    response = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={
            "worker": "w1",
            "description": "Attempted to attach another surface.",
            "status": "confirmed",
            "coverage_refs": [other["id"]],
        },
    )
    assert response.status_code == 409


def test_fact_verification_reference_is_persisted(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "verify", "origin": "https://example.test/", "goal": "g"},
    ).json()["project"]["id"]
    original = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "Initial controlled SQL injection evidence.",
            "vuln_type": "sql",
            "severity": "high",
            "status": "confirmed",
        },
    ).json()
    verified = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "Independent reproduction confirmed the same SQL injection.",
            "vuln_type": "sql",
            "severity": "high",
            "status": "verified",
            "verification_of": original["id"],
        },
    )
    assert verified.status_code == 201
    assert verified.json()["verification_of"] == original["id"]

    yaml_text = http_client.get(f"/projects/{pid}/export?format=yaml").text
    assert f"verification_of: {original['id']}" in yaml_text

def test_variant_results_wait_for_independent_verification(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "variants", "origin": "https://example.test/", "goal": "g", "mode": "real_website",
              "recon_profile": {"required_categories": []}},
    ).json()["project"]["id"]
    advanced = http_client.post(f"/projects/{pid}/phase/advance", json={})
    assert advanced.status_code == 200 and advanced.json()["advanced"]
    surface = create_surface(
        http_client, pid, fingerprint="surface-search", method="GET",
        path="/search", params=["q"], traits={"has_input": True},
    )
    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "param",
            "path": "/search",
            "param": "q",
            "description": "Search parameter security checks",
            "surface_group": surface["surface_group"],
            "surface_fingerprint": surface["fingerprint"],
            "test_family": "injection",
            "test_variants": ["sql", "xss"],
            "auth_context": surface["auth_context"],
            "required": True,
            "priority": 8,
        },
    ).json()

    def conclude(variant: str, status: str, description: str, *, source: str = "origin", verification_of: str | None = None):
        intent = http_client.post(
            f"/projects/{pid}/intents",
            json={
                "from": [source],
                "description": description,
                "creator": "w1",
                "worker": "w1",
                "coverage_refs": [coverage["id"]],
                "test_variant": variant,
                "action_kind": "verify" if verification_of else "security_test",
                "surface_ref": surface["id"],
                "surface_refs": [surface["id"]],
            },
        ).json()
        payload = {
            "worker": "w1",
            "description": description,
            "status": "reproduced" if verification_of else status,
            "vuln_type": variant,
            "coverage_refs": [coverage["id"]],
            "data": {"tested_surface_refs": [surface["id"]]},
        }
        if status in {"confirmed", "verified"}:
            payload["severity"] = "medium"
            payload["data"].update({
                "verify_request": "Independently reproduce the candidate.",
                "verify_requests": [{
                    "claim": "Independently reproduce the candidate.",
                    "surface_refs": [surface["id"]],
                    "evidence_refs": [],
                }],
            })
        if verification_of:
            payload["kind"] = "verification_result"
            payload["data"] = {"result": "reproduced", "attempts": [{"attempt": 1}]}
            payload["verification_of"] = verification_of
            payload["evidence_refs"] = ["task_log:manual-verification"]
        response = http_client.post(f"/projects/{pid}/intents/{intent['id']}/conclude", json=payload)
        assert response.status_code == 200
        return response.json()["fact"]

    positive = conclude("sql", "confirmed", "Boolean behavior confirmed SQL injection.")
    conclude("xss", "not_vulnerable", "Reflected input was encoded in the tested response contexts.")
    ledger = http_client.get(f"/projects/{pid}/coverage").json()[0]
    assert ledger["execution_status"] == "testing"
    assert ledger["outcome"] is None
    assert {item["variant"]: item["status"] for item in ledger["variant_results"]} == {
        "sql": "informational", "xss": "not_vulnerable",
    }
    assert http_client.get(f"/projects/{pid}/attack-paths").json() == []

    verification = conclude(
        "sql",
        "reproduced",
        "An independent time-delay probe reproduced the SQL injection.",
        source=positive["id"],
        verification_of=positive["id"],
    )
    ledger = http_client.get(f"/projects/{pid}/coverage").json()[0]
    assert ledger["execution_status"] == "completed"
    assert ledger["outcome"] == "vulnerable"
    assert http_client.get(f"/projects/{pid}/attack-paths").json() == []

    assert verification["verification_of"] == positive["id"]


def test_verification_rejects_a_different_variant(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "verify", "origin": "https://example.test/", "goal": "g"},
    ).json()["project"]["id"]
    original = http_client.post(
        f"/projects/{pid}/facts",
        json={"description": "SQL evidence.", "vuln_type": "sql", "status": "confirmed"},
    ).json()
    rejected = http_client.post(
        f"/projects/{pid}/facts",
        json={
            "description": "Unrelated XSS evidence.",
            "vuln_type": "xss",
            "status": "verified",
            "verification_of": original["id"],
        },
    )
    assert rejected.status_code == 409


def test_coverage_exclusion_is_optional_for_completion(http_client: TestClient) -> None:
    pid = http_client.post(
        "/projects",
        json={
            "title": "coverage waiver",
            "origin": "https://example.test/",
            "goal": "assess",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "recon_profile": {"required_categories": []},
        },
    ).json()["project"]["id"]
    assert http_client.post(f"/projects/{pid}/phase/advance", json={}).json()["advanced"]
    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "Authorization responsibility",
            "surface_group": "admin:users",
            "test_family": "authorization",
            "auth_context": "admin",
            "test_variants": ["vertical_access"],
            "priority": 9,
        },
    ).json()

    detail = http_client.get(f"/projects/{pid}").json()
    assert detail["project"]["completion_blockers"] == []
    excluded = http_client.post(
        f"/projects/{pid}/coverage/{coverage['id']}/exclude",
        json={"reason": "admin user management is excluded by the engagement", "creator": "human"},
    )
    assert excluded.status_code == 200
    assert excluded.json()["required"] is False
    assert excluded.json()["disposition"] == "excluded"
    assert excluded.json()["outcome"] == "not_applicable"
    assert excluded.json()["applicability_reason"].startswith("Excluded from required scope:")

    _claim_web_reason(http_client, pid)
    completed = http_client.post(
        f"/projects/{pid}/complete",
        json={"from": [], "description": "completed within scope", "worker": "reasoner"},
    )
    assert completed.status_code == 200


def test_structured_coverage_creation_merges_same_responsibility(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "merge", "origin": "https://example.test/", "goal": "assess"},
    ).json()["project"]["id"]
    first = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "Input validation",
            "surface_group": "web:/search",
            "test_family": "injection",
            "auth_context": "anonymous",
            "test_variants": ["sql"],
            "roles": ["anonymous"],
            "priority": 6,
        },
    ).json()
    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "test command injection",
            "creator": "reasoner",
            "test_variant": "sql",
            "coverage_refs": [first["id"]],
        },
    ).json()
    second = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "Same responsibility from a second surface observation",
            "surface_group": "web:/search",
            "test_family": "injection",
            "auth_context": "anonymous",
            "test_variants": ["command"],
            "roles": ["user"],
            "priority": 9,
            "intent_id": intent["id"],
        },
    ).json()

    assert second["id"] == first["id"]
    items = http_client.get(f"/projects/{pid}/coverage").json()
    assert len(items) == 1
    assert items[0]["priority"] == 9
    assert items[0]["test_variants"] == ["command", "sql"]
    assert items[0]["roles"] == ["anonymous", "user"]
    assert items[0]["intent_ids"] == [intent["id"]]


def test_legacy_duplicate_profile_coverage_merges_idempotently(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "legacy merge", "origin": "https://example.test/", "goal": "assess"},
    ).json()["project"]["id"]
    original = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "Injection responsibility",
            "surface_group": "web:/search",
            "test_family": "injection",
            "auth_context": "anonymous",
            "test_variants": ["sql"],
            "priority": 6,
        },
    ).json()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM coverage_items WHERE project_id = ? AND id = ?",
            (pid, original["id"]),
        ).fetchone()
        assert row is not None
        columns = list(row.keys())
        values = [row[column] for column in columns]
        values[columns.index("id")] = "cov999"
        values[columns.index("description")] = "Duplicate historical responsibility"
        values[columns.index("test_variants")] = json.dumps(["command"])
        values[columns.index("priority")] = 9
        conn.execute(
            f"INSERT INTO coverage_items ({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})",
            values,
        )
        first_change_count = reconcile_project_coverage(conn, pid)
        second_change_count = reconcile_project_coverage(conn, pid)

    items = http_client.get(f"/projects/{pid}/coverage").json()
    assert first_change_count > 0
    assert second_change_count == 0
    assert len(items) == 1
    assert items[0]["id"] == original["id"]
    assert items[0]["priority"] == 9
    assert items[0]["test_variants"] == ["command", "sql"]


def test_reconcile_does_not_infer_legacy_variant_evidence_from_binding(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={
            "title": "legacy binding",
            "origin": "https://example.test/",
            "goal": "assess",
            "mode": "real_website",
        },
    ).json()["project"]["id"]
    coverage = http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "param",
            "path": "/search",
            "param": "q",
            "description": "Search injection",
            "test_family": "injection",
            "test_variants": ["sql"],
            "priority": 7,
        },
    ).json()
    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "Verify SQL injection",
            "creator": "w1",
            "worker": "w1",
            "coverage_refs": [coverage["id"]],
            "test_variant": "sql",
        },
    ).json()
    concluded = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={
            "worker": "w1",
            "description": "SQL injection check completed.",
            "status": "confirmed",
            "severity": "high",
        },
    )
    assert concluded.status_code == 200

    with get_conn() as conn:
        conn.execute(
            "UPDATE coverage_items SET test_variants = ? WHERE project_id = ? AND id = ?",
            (json.dumps(["command"]), pid, coverage["id"]),
        )
        reconcile_project_coverage(conn, pid)

    item = http_client.get(f"/projects/{pid}/coverage").json()[0]
    assert item["intent_ids"] == [intent["id"]]
    assert concluded.json()["fact"]["id"] not in item["evidence_fact_ids"]
    assert item["execution_status"] == "untested"


def test_project_list_and_detail_ignore_legacy_attack_path_rows(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "legacy path", "origin": "o", "goal": "g"},
    ).json()["project"]["id"]
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO attack_paths (
                id, project_id, name, fact_chain, description, severity, status,
                suggested_status, status_reason, signature, created_at, updated_at
            ) VALUES ('ap001', ?, 'legacy', ?, 'legacy annotation', 'high',
                      'refuted', 'refuted', 'stale marker', 'legacy-signature',
                      '2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z')""",
            (pid, json.dumps(["origin"])),
        )

    assert http_client.get("/projects").status_code == 200
    assert http_client.get(f"/projects/{pid}").json()["attack_paths"] == []
    with get_conn() as conn:
        legacy = conn.execute(
            "SELECT status, status_reason FROM attack_paths WHERE project_id = ? AND id = 'ap001'",
            (pid,),
        ).fetchone()
        assert legacy is not None
        assert (legacy["status"], legacy["status_reason"]) == ("refuted", "stale marker")

def test_sqlite_connections_use_wal_and_busy_timeout(http_client: TestClient) -> None:
    with get_conn() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].casefold() == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 10000

def test_task_log_list_reads_bounded_previews_and_detail_keeps_full_output(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "bounded logs", "origin": "o", "goal": "g"},
    ).json()["project"]["id"]
    created = http_client.post(
        f"/projects/{pid}/logs",
        json={
            "task_type": "explore",
            "worker_name": "w1",
            "phase": "explore_execute",
            "stdin": "i" * 1000,
            "stdout": "o" * 1000,
            "stderr": "e" * 100000,
            "return_code": 1,
            "duration_ms": 10,
        },
    ).json()

    response = http_client.get(f"/projects/{pid}/logs")
    assert response.status_code == 200
    assert len(response.content) < 5000
    summary = response.json()[0]
    assert len(summary["stdin_preview"]) == 500
    assert len(summary["stdout_preview"]) == 500
    assert "stderr" not in summary

    detail = http_client.get(f"/projects/{pid}/logs/{created['id']}").json()
    assert len(detail["stdin"]) == 1000
    assert len(detail["stdout"]) == 1000
    assert len(detail["stderr"]) == 65536
    assert detail["stdout_truncated"] is False
    assert detail["stderr_truncated"] is True
    assert created["stderr_truncated"] is True

def test_report_keeps_confirmed_negative_failed_inconclusive_and_untested_separate(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "result classes", "origin": "https://example.test", "goal": "assess"},
    ).json()["project"]["id"]
    for status, description in (
        ("confirmed", "Confirmed SQL injection."),
        ("not_vulnerable", "Negative XSS test."),
        ("failed", "SQLMap process failed."),
        ("inconclusive", "Upload test timed out."),
    ):
        response = http_client.post(
            f"/projects/{pid}/facts",
            json={
                "description": description,
                "status": status,
                "vuln_type": "sql" if status == "confirmed" else None,
                "severity": "high" if status == "confirmed" else None,
            },
        )
        assert response.status_code == 201
    http_client.post(
        f"/projects/{pid}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "Untested CSRF responsibility",
            "surface_group": "web:/submit",
            "test_family": "session_csrf",
            "test_variants": ["csrf"],
            "priority": 6,
        },
    )

    report = http_client.get(f"/projects/{pid}/export?format=report").text
    assert "### Failed Tests" in report
    assert "### Inconclusive Tests" in report
    assert "### Negative Tests" in report
    assert "Variant csrf: untested" in report
    assert "Confirmed SQL injection." in report

def test_index_serves_attack_path_ui_as_utf8(http_client: TestClient) -> None:
    response = http_client.get("/")
    assert response.status_code == 200
    assert "charset=utf-8" in response.headers["content-type"].casefold()
    text = response.content.decode("utf-8")
    assert "已完成的因果攻击路径" in text
    assert "需要人工处理" in text


def test_concluded_fact_persists_its_execution_log_as_evidence(
    http_client: TestClient,
) -> None:
    pid = http_client.post(
        "/projects",
        json={"title": "evidence", "origin": "https://example.test", "goal": "assess"},
    ).json()["project"]["id"]
    intent = http_client.post(
        f"/projects/{pid}/intents",
        json={
            "from": ["origin"],
            "description": "Verify one concrete SQL injection hypothesis",
            "creator": "worker",
            "worker": "worker",
            "action_kind": "injection_hypothesis",
            "test_variant": "sql_injection",
        },
    ).json()
    task_log = http_client.post(
        f"/projects/{pid}/logs",
        json={
            "task_type": "explore",
            "intent_id": intent["id"],
            "worker_name": "worker",
            "phase": "explore_execute",
            "stdin": "send bounded boolean probes",
            "stdout": "baseline=200 true=200 false=500",
            "stderr": "",
            "return_code": 0,
            "duration_ms": 120,
        },
    ).json()
    concluded = http_client.post(
        f"/projects/{pid}/intents/{intent['id']}/conclude",
        json={
            "worker": "worker",
            "description": "The bounded boolean probe produced a repeatable response split.",
            "status": "confirmed",
            "vuln_type": "sql_injection",
            "severity": "high",
        },
    )
    assert concluded.status_code == 200
    fact = concluded.json()["fact"]
    assert f"task_log:{task_log['id']}" in fact["evidence_refs"]
    assert task_log["id"] in fact["task_log_refs"]


def _mixed_web_assessment_project(http_client: TestClient) -> str:
    created = http_client.post(
        "/projects",
        json={
            "title": "mixed report assessment",
            "origin": "https://example.test/",
            "goal": "assess",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "scope_policy": {
                "allowed_targets": ["example.test"],
                "allowed_ports": [443],
                "allow_destructive": True,
                "destructive_action_kinds": ["delete_test_record"],
                "destructive_test_identities": ["test-admin"],
                "destructive_test_data_refs": ["record:test-42"],
                "destructive_state_check_required": True,
            },
            "recon_profile": {"required_categories": []},
        },
    )
    assert created.status_code == 201
    project_id = created.json()["project"]["id"]
    with get_conn() as conn:
        conn.execute(
            "UPDATE projects SET planning_version = 3, phase = 'explore' WHERE id = ?",
            (project_id,),
        )

    surface = create_surface(http_client, project_id)
    coverage = [
        create_required_coverage(
            http_client, project_id, surface, family=family, variant=variant,
        )
        for family, variant in (
            ("identity_auth", "authentication_flow"),
            ("session_csrf", "csrf_state_change"),
            ("injection", "sql_injection"),
            ("business_logic", "workflow_invariant"),
        )
    ]
    retrying = create_intent(
        http_client, project_id, surface=surface,
        coverage_ids=[coverage[2]["id"]], test_variant="sql_injection",
    )
    claim_intent(http_client, project_id, retrying["id"])
    assert http_client.post(
        f"/projects/{project_id}/intents/{retrying['id']}/failure",
        json={
            "worker": "executor", "error": "tool transport failed",
            "max_attempts": 3, "backoff_seconds": 60,
        },
    ).status_code == 200

    for index, result in enumerate(("reproduced", "not_reproduced")):
        variant = coverage[index]["test_variants"][0]
        explore = create_intent(
            http_client, project_id, surface=surface,
            coverage_ids=[coverage[index]["id"]], test_variant=variant,
        )
        claim_intent(http_client, project_id, explore["id"])
        candidate = conclude_intent(
            http_client, project_id, explore["id"],
            description=f"Candidate for {result}",
            data={
                "tested_surface_refs": [surface["id"]],
                "verify_request": f"verify {result}",
                "verify_requests": [{
                    "claim": f"verify {result}",
                    "surface_refs": [surface["id"]],
                    "evidence_refs": [],
                }],
            },
        )["fact"]
        verify = create_intent(
            http_client, project_id, surface=surface,
            coverage_ids=[coverage[index]["id"]], action_kind="verify",
            test_variant=variant, from_ids=[candidate["id"]],
        )
        claim_intent(http_client, project_id, verify["id"], worker="verifier")
        conclude_intent(
            http_client, project_id, verify["id"], worker="verifier",
            description=f"Verify result: {result}", status=result,
            verification_of=candidate["id"], parent_fact=candidate["id"],
            kind="verification_result", data={"result": result, "attempts": []},
            evidence_refs=[f"task_log:{result}"],
            coverage_refs=[coverage[index]["id"]],
        )

    mapped = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"], "description": "Map health endpoint only.",
            "creator": "reasoner", "action_kind": "surface_mapping",
            "test_variant": "surface_mapping",
        },
    ).json()
    claim_intent(http_client, project_id, mapped["id"])
    mapped_fact = conclude_intent(
        http_client, project_id, mapped["id"],
        description="Mapped health endpoint without security testing.",
    )["fact"]
    create_surface(
        http_client, project_id, fingerprint="surface-health", method="GET",
        path="/health", params=[], traits={"static": True},
        source_fact_id=mapped_fact["id"],
    )

    high_risk = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "Authorized disposable record deletion.",
            "creator": "reasoner", "target": "example.test", "port": 443,
            "path": "/test-records/42", "action_kind": "delete_test_record",
            "risk_level": "high", "test_identity": "test-admin",
            "test_data_refs": ["record:test-42"],
        },
    )
    assert high_risk.status_code == 201
    return project_id


def test_web_report_separates_behavior_coverage_verify_and_retry(http_client):
    project_id = _mixed_web_assessment_project(http_client)
    report = http_client.get(f"/projects/{project_id}/export?format=report").text

    assert "## Behavior Coverage" in report
    assert "Required Coverage: 4" in report
    assert "Completed Coverage: 2" in report
    assert "## Retrying Coverage" in report
    assert "## Reproduced Findings" in report
    assert "## Not Reproduced Candidates" in report
    assert "## Authorized High-Risk Tests" in report
    assert "Mapped-only Surfaces tested: 0" in report
    assert "dispatch deduplication key" in report
    assert "target idempotency key" not in report
