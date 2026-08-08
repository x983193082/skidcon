from __future__ import annotations

from fastapi.testclient import TestClient


def _real_project(http: TestClient, required: list[str]) -> str:
    response = http.post(
        "/projects",
        json={
            "title": "state machine",
            "origin": "https://example.test/",
            "goal": "assess",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "recon_profile": {
                "required_categories": required,
                "disabled_categories": [],
            },
        },
    )
    assert response.status_code == 201
    return response.json()["project"]["id"]


def _conclude(
    http: TestClient,
    project_id: str,
    *,
    description: str,
    action_kind: str | None = None,
) -> dict:
    body = {
        "from": ["origin"],
        "description": description,
        "creator": "reasoner",
    }
    if action_kind is not None:
        body["action_kind"] = action_kind
    intent = http.post(f"/projects/{project_id}/intents", json=body)
    assert intent.status_code == 201
    intent_id = intent.json()["id"]
    heartbeat = http.post(
        f"/projects/{project_id}/intents/{intent_id}/heartbeat",
        json={"worker": "worker"},
    )
    assert heartbeat.status_code == 200
    result = http.post(
        f"/projects/{project_id}/intents/{intent_id}/conclude",
        json={"worker": "worker", "description": f"finished: {description}"},
    )
    assert result.status_code == 200
    return result.json()["fact"]


def test_conclusion_derives_structured_recon_and_server_advances_phase(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, ["port_scan"])
    fact = _conclude(
        http_client,
        project_id,
        description="collect service inventory",
        action_kind="port_scan",
    )

    assert fact["recon_category"] == "port_scan"
    assert fact["recon_executed"] is True
    transition = http_client.post(f"/projects/{project_id}/phase/advance", json={})
    assert transition.status_code == 200
    assert transition.json()["advanced"] is True
    assert http_client.get(f"/projects/{project_id}").json()["project"]["phase"] == "explore"


def test_legacy_recon_prose_is_backfilled_once_before_structured_gate(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, ["port_scan"])
    fact = _conclude(
        http_client,
        project_id,
        description="Run an nmap port scan and record service enumeration.",
    )
    assert fact["recon_category"] is None

    transition = http_client.post(f"/projects/{project_id}/phase/advance", json={})
    assert transition.status_code == 200
    assert transition.json()["advanced"] is True
    facts = {
        item["id"]: item
        for item in http_client.get(f"/projects/{project_id}").json()["facts"]
    }
    assert facts[fact["id"]]["recon_category"] == "port_scan"
    assert facts[fact["id"]]["recon_executed"] is True


def test_dispatch_view_skips_full_completion_enrichment(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, [])
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).json()["advanced"]
    coverage = http_client.post(
        f"/projects/{project_id}/coverage",
        json={
            "item_type": "param",
            "description": "required SQL check",
            "test_family": "injection",
            "test_variants": ["sql"],
            "priority": 8,
        },
    )
    assert coverage.status_code == 201

    dispatch = http_client.get(f"/projects/{project_id}?view=dispatch")
    full = http_client.get(f"/projects/{project_id}?view=full")
    assert dispatch.status_code == full.status_code == 200
    assert dispatch.json()["project"]["completion_blockers"] == []
    blockers = full.json()["project"]["completion_blockers"]
    assert blockers == []


def test_recon_reports_only_the_stage_gate_not_future_assessment_work(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, ["port_scan", "directory", "asset"])
    surface = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "legacy-planned-surface",
            "surface_group": "auth:/admin",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/admin",
            "surface_type": "admin_route",
            "auth_context": "admin",
            "traits": {"admin": True},
        },
    )
    assert surface.status_code == 200
    for index, family in enumerate(
        ["identity_auth", "authorization", "session_csrf", "file_path", "injection"],
        start=1,
    ):
        coverage = http_client.post(
            f"/projects/{project_id}/coverage",
            json={
                "item_type": "vuln_class",
                "description": f"premature {family} coverage",
                "surface_fingerprint": "legacy-planned-surface",
                "test_family": family,
                "test_variants": [f"variant-{index}"],
                "required": True,
                "priority": 8,
            },
        )
        assert coverage.status_code == 201

    full = http_client.get(f"/projects/{project_id}?view=full").json()
    blockers = full["project"]["completion_blockers"]
    assert blockers == []

    active_report = http_client.get(f"/projects/{project_id}/export?format=report").text
    assert "Structured recon is in progress" in active_report
    assert "reason/project-phase" not in active_report

    premature = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": ["origin"], "description": "premature", "worker": "reasoner"},
    )
    assert premature.status_code == 409
    assert [item["ref"] for item in premature.json()["detail"]["blockers"]] == [
        "project-phase"
    ]

    stopped = http_client.put(
        f"/projects/{project_id}/status", json={"status": "stopped"},
    )
    assert stopped.status_code == 200
    assert len(stopped.json()["completion_blockers"]) == 1
    after_stop = http_client.get(f"/projects/{project_id}?view=full").json()
    assert after_stop["project"]["completion_blockers"] == stopped.json()["completion_blockers"]
    stopped_report = http_client.get(f"/projects/{project_id}/export?format=report").text
    assert "reason/project-phase" in stopped_report


def test_reason_success_is_not_reclaimed_until_semantic_state_changes(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, [])
    claimed = http_client.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": "reasoner", "trigger": "initial"},
    )
    assert claimed.status_code == 200
    success = http_client.post(
        f"/projects/{project_id}/reason/success",
        json={"worker": "reasoner"},
    )
    assert success.status_code == 200

    duplicate = http_client.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": "reasoner", "trigger": "initial"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "reason_state_unchanged"

    hint = http_client.post(
        f"/projects/{project_id}/hints",
        json={"content": "new authorized context", "creator": "operator"},
    )
    assert hint.status_code == 201
    changed = http_client.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": "reasoner", "trigger": "hint"},
    )
    assert changed.status_code == 200

    assert http_client.post(
        f"/projects/{project_id}/reason/success",
        json={"worker": "reasoner"},
    ).status_code == 200
    duplicate_hint = http_client.post(
        f"/projects/{project_id}/hints",
        json={"content": "new authorized context", "creator": "operator"},
    )
    assert duplicate_hint.status_code == 201
    unchanged = http_client.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": "reasoner", "trigger": "duplicate hint"},
    )
    assert unchanged.status_code == 409
    assert unchanged.json()["detail"]["code"] == "reason_state_unchanged"


def _claim_reason(http: TestClient, project_id: str, worker: str = "reasoner") -> None:
    claimed = http.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": worker, "trigger": "test completion decision"},
    )
    assert claimed.status_code == 200


def _reproduced_verification(http: TestClient, project_id: str) -> tuple[dict, dict]:
    candidate = _conclude(
        http,
        project_id,
        description="test one reflected-input boundary",
        action_kind="xss_probe",
    )
    verify_intent = http.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [candidate["id"]],
            "description": "independently reproduce the reflected security impact",
            "creator": "reasoner",
            "action_kind": "verify_candidate",
        },
    )
    assert verify_intent.status_code == 201
    verify_id = verify_intent.json()["id"]
    assert http.post(
        f"/projects/{project_id}/intents/{verify_id}/heartbeat",
        json={"worker": "verifier"},
    ).status_code == 200
    verification = http.post(
        f"/projects/{project_id}/intents/{verify_id}/conclude",
        json={
            "worker": "verifier",
            "description": "Fresh session reproduced controlled script execution.",
            "status": "reproduced",
            "verification_of": candidate["id"],
            "kind": "verification_result",
            "data": {"result": "reproduced", "attempts": [{"attempt": 1}]},
        },
    )
    assert verification.status_code == 200
    return candidate, verification.json()["fact"]


def test_web_completion_requires_current_reason_claim(http_client: TestClient) -> None:
    project_id = _real_project(http_client, [])
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).json()["advanced"]

    response = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": [], "description": "assessment exhausted", "worker": "reasoner"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "completion_requires_reason"


def test_web_completion_blocks_only_an_orphan_verify_handoff(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, [])
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).json()["advanced"]
    candidate_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "probe one reflected-input candidate",
            "creator": "reasoner",
            "action_kind": "xss_probe",
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{candidate_intent['id']}/heartbeat",
        json={"worker": "explorer"},
    ).status_code == 200
    candidate = http_client.post(
        f"/projects/{project_id}/intents/{candidate_intent['id']}/conclude",
        json={
            "worker": "explorer",
            "description": "The tested marker reached an executable response context.",
            "data": {"verify_request": "Repeat the request in a fresh session."},
        },
    ).json()["fact"]
    _claim_reason(http_client, project_id)

    blocked = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": [], "description": "premature", "worker": "reasoner"},
    )
    assert blocked.status_code == 409
    assert [item["ref"] for item in blocked.json()["detail"]["blockers"]] == [
        f"verify:{candidate['id']}"
    ]

    assert http_client.post(
        f"/projects/{project_id}/reason/release",
        json={"worker": "reasoner"},
    ).status_code == 200
    verify = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [candidate["id"]],
            "description": "Repeat the request in a fresh session.",
            "creator": "reasoner",
            "action_kind": "verify_candidate",
        },
    )
    assert verify.status_code == 201
    blockers = http_client.get(f"/projects/{project_id}?view=full").json()["project"]["completion_blockers"]
    assert len(blockers) == 1
    assert blockers[0]["ref"] == verify.json()["id"]


def test_web_completion_rejects_non_verification_fact_source(http_client: TestClient) -> None:
    project_id = _real_project(http_client, [])
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).json()["advanced"]
    candidate = _conclude(
        http_client,
        project_id,
        description="objective candidate observation",
        action_kind="xss_probe",
    )
    _claim_reason(http_client, project_id)

    response = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": [candidate["id"]], "description": "invalid source", "worker": "reasoner"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "invalid_completion_source"


def test_reproduced_verification_builds_only_real_causal_attack_path(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, [])
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).json()["advanced"]
    candidate, verification = _reproduced_verification(http_client, project_id)
    _claim_reason(http_client, project_id)

    completed = http_client.post(
        f"/projects/{project_id}/complete",
        json={
            "from": [verification["id"]],
            "description": "Reason selected the reproduced verification.",
            "worker": "reasoner",
        },
    )
    assert completed.status_code == 200

    paths = http_client.get(f"/projects/{project_id}/attack-paths").json()
    assert len(paths) == 1
    assert paths[0]["fact_chain"] == ["origin", candidate["id"], verification["id"], "goal"]
    assert len(paths[0]["intent_refs"]) == 3


def test_report_counts_all_completion_findings_when_attack_paths_compress_ancestors(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, [])
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).json()["advanced"]
    _candidate_one, verification_one = _reproduced_verification(http_client, project_id)

    chained_candidate_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [verification_one["id"]],
            "description": "test a separate impact reachable after the first reproduced finding",
            "creator": "reasoner",
            "action_kind": "authorization_probe",
        },
    )
    assert chained_candidate_intent.status_code == 201
    chained_candidate_id = chained_candidate_intent.json()["id"]
    assert http_client.post(
        f"/projects/{project_id}/intents/{chained_candidate_id}/heartbeat",
        json={"worker": "worker"},
    ).status_code == 200
    chained_candidate = http_client.post(
        f"/projects/{project_id}/intents/{chained_candidate_id}/conclude",
        json={
            "worker": "worker",
            "description": "A second independent authorization impact was observed.",
        },
    )
    assert chained_candidate.status_code == 200
    chained_candidate_fact = chained_candidate.json()["fact"]

    verify_two_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [chained_candidate_fact["id"]],
            "description": "independently reproduce the second impact",
            "creator": "reasoner",
            "action_kind": "verify_candidate",
        },
    )
    assert verify_two_intent.status_code == 201
    verify_two_id = verify_two_intent.json()["id"]
    assert http_client.post(
        f"/projects/{project_id}/intents/{verify_two_id}/heartbeat",
        json={"worker": "verifier"},
    ).status_code == 200
    verification_two_response = http_client.post(
        f"/projects/{project_id}/intents/{verify_two_id}/conclude",
        json={
            "worker": "verifier",
            "description": "Fresh session reproduced the second authorization impact.",
            "status": "reproduced",
            "verification_of": chained_candidate_fact["id"],
            "kind": "verification_result",
        },
    )
    assert verification_two_response.status_code == 200
    verification_two = verification_two_response.json()["fact"]

    _claim_reason(http_client, project_id)
    completed = http_client.post(
        f"/projects/{project_id}/complete",
        json={
            "from": [verification_one["id"], verification_two["id"]],
            "description": "complete from both reproduced findings",
            "worker": "reasoner",
        },
    )
    assert completed.status_code == 200

    paths = http_client.get(f"/projects/{project_id}/attack-paths").json()
    assert len(paths) == 1
    report = http_client.get(f"/projects/{project_id}/export?format=report").text
    assert "- Independently reproduced security findings: 2" in report
    assert f"- Terminal Fact: {verification_one['id']}" in report
    assert f"- Terminal Fact: {verification_two['id']}" in report



def test_reason_can_complete_without_attack_path_when_nothing_reproduced(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, [])
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).json()["advanced"]
    _claim_reason(http_client, project_id)
    completed = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": [], "description": "No vulnerability reproduced.", "worker": "reasoner"},
    )
    assert completed.status_code == 200
    assert http_client.get(f"/projects/{project_id}/attack-paths").json() == []


def test_web_report_separates_reproduction_mapping_and_graph_surface_coverage(
    http_client: TestClient,
) -> None:
    project_id = _real_project(http_client, [])
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).json()["advanced"]
    mapping = _conclude(
        http_client,
        project_id,
        description="inventory the public application routes",
        action_kind="asset_discovery",
    )
    candidate, reproduced = _reproduced_verification(http_client, project_id)
    negative_candidate = _conclude(
        http_client,
        project_id,
        description="candidate SQL behavior needs independent verification",
        action_kind="sql_probe",
    )
    negative_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [negative_candidate["id"]],
            "description": "retry the SQL candidate in fresh sessions",
            "creator": "reasoner",
            "action_kind": "verify_candidate",
            "target": "https://example.test/search",
        },
    )
    assert negative_intent.status_code == 201
    negative_intent_id = negative_intent.json()["id"]
    assert http_client.post(
        f"/projects/{project_id}/intents/{negative_intent_id}/heartbeat",
        json={"worker": "verifier"},
    ).status_code == 200
    negative = http_client.post(
        f"/projects/{project_id}/intents/{negative_intent_id}/conclude",
        json={
            "worker": "verifier",
            "description": "Three fresh sessions did not reproduce the SQL behavior.",
            "status": "not_reproduced",
            "verification_of": negative_candidate["id"],
            "kind": "verification_result",
            "data": {
                "result": "not_reproduced",
                "attempts": [{"attempt": 1}, {"attempt": 2}, {"attempt": 3}],
            },
        },
    )
    assert negative.status_code == 200
    negative_fact = negative.json()["fact"]

    surface = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "route-home",
            "surface_group": "route:GET:/",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/",
            "surface_type": "route",
            "source_fact_id": mapping["id"],
            "evidence_fact_ids": [candidate["id"]],
        },
    )
    assert surface.status_code == 200
    tested_surface_id = surface.json()["id"]
    untested_surface = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "route-untested",
            "surface_group": "route:GET:/untested",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/untested",
            "surface_type": "route",
            "source_fact_id": mapping["id"],
            "evidence_fact_ids": [candidate["id"]],
        },
    )
    assert untested_surface.status_code == 200
    untested_surface_id = untested_surface.json()["id"]

    security_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [mapping["id"]],
            "description": "test the mapped home route",
            "creator": "reasoner",
            "action_kind": "security_probe",
            "target": "example.test",
            "path": "/",
            "surface_ref": tested_surface_id,
        },
    )
    assert security_intent.status_code == 201
    security_intent_id = security_intent.json()["id"]
    assert http_client.post(
        f"/projects/{project_id}/intents/{security_intent_id}/heartbeat",
        json={"worker": "worker"},
    ).status_code == 200
    assert http_client.post(
        f"/projects/{project_id}/intents/{security_intent_id}/conclude",
        json={
            "worker": "worker",
            "description": "The assigned home-route security test completed without a candidate finding.",
        },
    ).status_code == 200
    _claim_reason(http_client, project_id)
    completed = http_client.post(
        f"/projects/{project_id}/complete",
        json={
            "from": [reproduced["id"]],
            "description": "finish from the independently reproduced result",
            "worker": "reasoner",
        },
    )
    assert completed.status_code == 200

    report_response = http_client.get(f"/projects/{project_id}/export?format=report")
    assert report_response.status_code == 200
    assert "charset=utf-8" in report_response.headers["content-type"].casefold()
    report = report_response.content.decode("utf-8")
    assert "## Independently Reproduced Security Findings" in report
    assert "Fresh session reproduced controlled script execution." in report
    assert "## Executed Tests Without Reproduction" in report
    assert "Three fresh sessions did not reproduce the SQL behavior." in report
    assert "## Mapping And Recon Evidence" in report
    assert "inventory the public application routes" in report
    assert "## Surface Coverage" in report
    assert f"- {tested_surface_id} (GET /): graph_state=mapped / security_tested" in report
    assert f"- {untested_surface_id} (GET /untested): graph_state=mapped / not_tested" in report
    assert "- Status: complete" in report
    assert "- Suggested status: complete" not in report
    assert "## Untested And Limited Items" in report
    assert "Goal-linked findings" not in report
    assert "confirmed security findings" not in report.casefold()

    detail = http_client.get(f"/projects/{project_id}").json()
    paths = detail["attack_paths"]
    assert len(paths) == 1
    assert paths[0]["fact_chain"][-2:] == [reproduced["id"], "goal"]
    assert negative_fact["id"] not in paths[0]["fact_chain"]
