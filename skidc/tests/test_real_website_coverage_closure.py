from __future__ import annotations

import json

from fastapi.testclient import TestClient

from skidc.planning import behavior_identity, cluster_behaviors, derive_candidates
from skidc.dispatcher.prompting import format_dispatch_graph
from skidc.dispatcher.protocol.client import ApiResult
from skidc.dispatcher.tasks.explore import _with_web_fact_output_rules
from skidc.dispatcher.tasks.reason import (
    _bind_matching_coverage,
    _bind_matching_surface,
    _create_agent_hypothesis_work,
    _ensure_pending_surface_mapping_work,
    _intent_signature_from_data,
    _select_v3_frontier,
    _with_web_reason_planning_rules,
    ensure_coverage_work,
)
from skidc.server.db import get_conn
from tests.conftest import InProcessClient
from tests.support.web_assessment import (
    claim_intent,
    claim_reason,
    conclude_intent,
    create_intent,
    create_real_web_project,
    create_required_coverage,
    create_surface,
)

def _claim_reason(http: TestClient, project_id: str, worker: str = "reasoner") -> None:
    response = http.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": worker, "trigger": "test completion"},
    )
    assert response.status_code == 200


def test_web_conclusion_without_explicit_tested_refs_does_not_test_surface(http_client):
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
        description="CAPTCHA prerequisite confirmed; testing is incomplete.",
    )
    assert "tested_surface_refs" not in concluded["fact"]["data"]
    current = http_client.get(f"/projects/{project_id}/surfaces").json()[0]
    assert current["graph_testing_status"] == "not_tested"


def test_important_behavior_requires_every_required_surface_coverage(http_client):
    project_id = create_real_web_project(http_client)
    surface = create_surface(
        http_client,
        project_id,
        fingerprint="surface-session",
        method="GET",
        path="/session",
        params=[],
        surface_type="route",
        traits={"auth": True},
    )
    first = create_required_coverage(
        http_client,
        project_id,
        surface,
        family="identity_auth",
        variant="authentication_flow",
    )
    second = create_required_coverage(
        http_client,
        project_id,
        surface,
        family="session_csrf",
        variant="csrf_state_change",
    )
    intent = create_intent(
        http_client,
        project_id,
        surface=surface,
        coverage_ids=[first["id"]],
        test_variant="authentication_flow",
    )
    claim_intent(http_client, project_id, intent["id"])
    conclude_intent(
        http_client,
        project_id,
        intent["id"],
        description="Authentication checks produced a clean negative result.",
        data={"tested_surface_refs": [surface["id"]]},
    )
    claim_reason(http_client, project_id)
    response = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": [], "description": "premature", "worker": "reasoner"},
    )
    assert response.status_code == 409
    blockers = response.json()["detail"]["blockers"]
    assert [item["ref"] for item in blockers if item["kind"] == "coverage"] == [
        second["id"]
    ]


def test_high_value_behavior_with_missing_profile_is_blocked(http_client):
    project_id = create_real_web_project(http_client)
    surface = create_surface(
        http_client,
        project_id,
        fingerprint="surface-session",
        method="GET",
        path="/session",
        params=[],
        surface_type="route",
        traits={"auth": True},
    )
    blockers = http_client.get(
        f"/projects/{project_id}?view=full"
    ).json()["project"]["completion_blockers"]
    assert any(
        item["kind"] == "coverage"
        and item["status"] == "profile_missing"
        and surface["id"] in item["related_refs"]
        for item in blockers
    )


def test_informational_does_not_complete_required_surface_coverage(http_client):
    project_id = create_real_web_project(http_client)
    surface = create_surface(
        http_client,
        project_id,
        fingerprint="surface-session",
        method="GET",
        path="/session",
        params=[],
        surface_type="route",
        traits={"auth": True},
    )
    coverage = create_required_coverage(
        http_client,
        project_id,
        surface,
        family="identity_auth",
        variant="authentication_flow",
    )
    with get_conn() as conn:
        conn.execute(
            "UPDATE surface_inventory SET planning_status='assessed' "
            "WHERE project_id=? AND id=?",
            (project_id, surface["id"]),
        )
        conn.execute(
            "UPDATE coverage_items SET execution_status='completed', outcome='informational' "
            "WHERE project_id=? AND id=?",
            (project_id, coverage["id"]),
        )
    current = http_client.get(f"/projects/{project_id}/surfaces").json()[0]
    assert current["completed_coverage_count"] == 0
    assert current["test_status"] != "completed"




def _create_real_project(
    http: TestClient,
    *,
    origin: str = "https://example.test/",
    max_intents: int = 20,
    batch_size: int = 20,
    enter_explore: bool = True,
    planning_version: int = 2,
) -> str:
    response = http.post(
        "/projects",
        json={
            "title": "coverage closure",
            "origin": origin,
            "goal": "assess the authorized target",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "scope_policy": {
                "allowed_targets": ["example.test"],
                "allowed_ports": [80, 443],
            },
            "recon_profile": {
                "target_type": "domain",
                "required_categories": [],
                "optional_categories": [],
                "disabled_categories": ["port_scan", "subdomain", "directory", "asset"],
                "max_coverage_intents": max_intents,
                "coverage_batch_size": batch_size,
            },
        },
    )
    project_id = response.json()["project"]["id"]
    assert response.status_code == 201
    if planning_version != 3:
        with get_conn() as conn:
            conn.execute(
                "UPDATE projects SET planning_version = ? WHERE id = ?", (planning_version, project_id)
            )
    if enter_explore:
        phase = http.put(f"/projects/{project_id}/phase", json={"phase": "explore"})
        assert phase.status_code == 200
    return project_id


def _create_injection_coverage(http: TestClient, project_id: str, variants: list[str]):
    response = http.post(
        f"/projects/{project_id}/coverage",
        json={
            "item_type": "param",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path": "/search",
            "param": "q",
            "description": "Test the search input across all declared injection variants.",
            "surface_group": "search input",
            "surface_fingerprint": "surface-search-get-anonymous",
            "test_family": "injection",
            "test_variants": variants,
            "auth_context": "anonymous",
            "priority": 8,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_real_project_cannot_complete_before_recon_transition(http_client: TestClient) -> None:
    project_id = _create_real_project(http_client, enter_explore=False)

    completed = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": ["origin"], "description": "premature", "worker": "reasoner"},
    )

    assert completed.status_code == 409
    blockers = completed.json()["detail"]["blockers"]
    assert any(item["ref"] == "project-phase" for item in blockers)


def test_recon_reason_drops_model_supplied_coverage_category(http_client: TestClient) -> None:
    project_id = _create_real_project(http_client, enter_explore=False, planning_version=3)
    project = InProcessClient(http_client).get_project(project_id)

    sanitized = _bind_matching_coverage(
        project,
        {
            "from": ["origin"],
            "description": "inventory public assets",
            "action_kind": "asset_discovery",
            "coverage_refs": ["asset"],
        },
    )

    assert "coverage_refs" not in sanitized


def test_v2_planner_keeps_failed_required_work_retryable_and_blocks_completion(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client)
    surface = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "account-update-post",
            "surface_group": "account update",
            "target": "example.test",
            "port": 443,
            "method": "POST",
            "path_template": "/account/{id}",
            "params": ["id", "callback_url"],
            "auth_context": "session",
            "source_fact_id": "origin",
        },
    )
    assert surface.status_code == 200
    client = InProcessClient(http_client)

    before = client.get_project(project_id)
    assert before.project.planning_version == 2
    assert ensure_coverage_work(client, before, "reasoner") == 3
    planned = client.get_project(project_id)
    assert ensure_coverage_work(client, planned, "reasoner") == 0
    assert len(planned.hypotheses) == 3
    assert {item.test_variant for item in planned.hypotheses} == {
        "object_boundary", "ssrf", "csrf_state_change",
    }
    assert len(planned.coverage_items) == 3
    assert all(len(item.test_variants) == 1 for item in planned.coverage_items)
    assert all(intent.hypothesis_id for intent in planned.intents)

    report = http_client.get(f"/projects/{project_id}/export?format=report")
    assert report.status_code == 200
    assert "## Hypothesis Plan" in report.text
    assert "## Assessment Limitations" in report.text
    assert all(item.id in report.text for item in planned.hypotheses)

    for failed_intent in planned.intents:
        failed = http_client.post(
            f"/projects/{project_id}/intents/{failed_intent.id}/failure",
            json={"worker": "worker", "error": "bounded execution failed", "max_attempts": 1},
        )
        assert failed.status_code == 200
        assert failed.json()["status"] == "open"
        assert failed.json()["to"] is None
        assert failed.json()["dead_lettered_at"] is None
    failed_intent = planned.intents[0]

    detail = client.get_project(project_id)
    failed_hypothesis = next(
        item for item in detail.hypotheses if item.id == failed_intent.hypothesis_id
    )
    assert failed_hypothesis.status == "planned"
    assert client.claim_reason(project_id, "reasoner", "bounded work exhausted").ok
    completed = client.complete(
        project_id, [], "required work has not produced evidence", "reasoner",
    )
    assert not completed.ok
    assert completed.status_code == 409


def test_work_identity_deduplicates_primary_but_allows_explicit_verification(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client)
    coverage = _create_injection_coverage(http_client, project_id, ["sql"])
    payload = {
        "from": ["origin"],
        "description": "primary SQL probe",
        "creator": "reasoner",
        "coverage_refs": [coverage["id"]],
        "test_variant": "sql",
        "action_kind": "injection_probe",
    }
    first = http_client.post(f"/projects/{project_id}/intents", json=payload)
    second = http_client.post(f"/projects/{project_id}/intents", json={**payload, "description": "replacement"})
    candidate = http_client.post(
        f"/projects/{project_id}/facts",
        json={"description": "Candidate SQL behavior requiring independent reproduction."},
    )
    assert candidate.status_code == 201
    verification = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            **payload,
            "from": [candidate.json()["id"]],
            "description": "independent verification",
            "action_kind": "verification_probe",
        },
    )

    assert first.status_code == second.status_code == verification.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert verification.json()["id"] != first.json()["id"]


def test_conclusion_surfaces_become_inventory_without_completion_deadlock(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client)
    intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "discover routes",
            "creator": "reasoner",
            "action_kind": "asset_discovery",
        },
    ).json()
    http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/heartbeat", json={"worker": "worker"}
    )
    concluded = http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/conclude",
        json={
            "worker": "worker",
            "description": "A POST upload surface was observed.",
            "status": "informational",
            "observed_surfaces": [{
                "method": "POST",
                "path": "/v1/upload",
                "params": ["file"],
                "auth_context": "authenticated",
                "surface_type": "upload_point",
            }],
        },
    )
    assert concluded.status_code == 200
    surfaces = http_client.get(f"/projects/{project_id}/surfaces").json()
    assert [(item["method"], item["path_template"]) for item in surfaces] == [("POST", "/v1/upload")]
    assert surfaces[0]["fingerprint"] != "upload-post-authenticated"
    assert surfaces[0]["surface_group"]
    assert surfaces[0]["target"] == "example.test"
    assert surfaces[0]["port"] == 443

    _claim_reason(http_client, project_id)
    completed = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": [], "description": "complete with pending surface recorded", "worker": "reasoner"},
    )
    assert completed.status_code == 200
    report = http_client.get(f"/projects/{project_id}/export?format=report").text
    assert "## Assessment Limitations" in report


def test_v3_pending_function_gets_one_mapping_intent_and_result_fact(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    surface = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "admin-edit-post",
            "surface_group": "admin edit",
            "target": "example.test",
            "port": 443,
            "method": "POST",
            "path_template": "/admin.php?r=edit",
            "params": ["id", "title"],
            "auth_context": "admin",
            "surface_type": "admin_route",
            "source_fact_id": "origin",
        },
    )
    assert surface.status_code == 200
    client = InProcessClient(http_client)
    project = client.get_project(project_id)

    assert _ensure_pending_surface_mapping_work(
        client, project, "reasoner", max_items=1,
    ) == 1
    mapped = client.get_project(project_id)
    assert mapped.surface_inventory[0].planning_status == "assessed"
    assert len(mapped.intents) == 1
    intent = mapped.intents[0]
    assert intent.action_kind == "surface_discovery"
    assert intent.test_variant == "function_mapping"

    failed = http_client.post(
        f"/projects/{project_id}/intents/{intent.id}/failure",
        json={
            "worker": "worker",
            "error": "mapping worker timed out",
            "max_attempts": 1,
            "backoff_seconds": 0,
        },
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "open"
    detail = client.get_project(project_id)
    assert failed.json()["to"] is None
    assert failed.json()["dead_lettered_at"] is None
    assert len(detail.facts) == 2

def test_v3_ignores_legacy_surface_and_coverage_without_fact_evidence(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    fingerprint = "legacy-intent-derived-surface"
    assert http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": fingerprint,
            "surface_group": "upload:/admin",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/admin",
            "surface_type": "upload_point",
            "traits": {"admin": True, "upload": True},
        },
    ).status_code == 200
    assert http_client.post(
        f"/projects/{project_id}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "Legacy coverage inferred from an Intent description.",
            "surface_fingerprint": fingerprint,
            "test_family": "file_path",
            "test_variants": ["upload"],
            "required": True,
        },
    ).status_code == 201

    client = InProcessClient(http_client)
    assert ensure_coverage_work(client, client.get_project(project_id), "dispatcher") == 0
    refreshed = client.get_project(project_id)
    assert refreshed.hypotheses == []
    assert refreshed.intents == []
    full = http_client.get(f"/projects/{project_id}?view=full").json()
    assert full["project"]["completion_blockers"] == []
    assert full["surface_inventory"][0]["test_status"] == "unassessed"

def test_v3_surface_index_does_not_create_mapping_or_security_work(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    for surface in (
        {
            "fingerprint": "account-update-post",
            "surface_group": "account update",
            "target": "example.test",
            "port": 443,
            "method": "POST",
            "path_template": "/account/{id}",
            "params": ["id", "callback_url"],
            "auth_context": "session",
            "surface_type": "form",
            "source_fact_id": "origin",
        },
        {
            "fingerprint": "search-get",
            "surface_group": "search",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/search",
            "params": ["q"],
            "auth_context": "anonymous",
            "surface_type": "route",
            "source_fact_id": "origin",
        },
    ):
        assert http_client.post(
            f"/projects/{project_id}/surfaces", json=surface,
        ).status_code == 200

    client = InProcessClient(http_client)
    before = client.get_project(project_id)
    assert len(before.surface_inventory) == 2

    assert ensure_coverage_work(client, before, "dispatcher") == 0

    after = client.get_project(project_id)
    assert len(after.surface_inventory) == 2
    assert after.intents == []
    assert after.hypotheses == []
    assert after.coverage_items == []
    assert {
        (surface.fingerprint, surface.planning_status)
        for surface in after.surface_inventory
    } == {
        (surface.fingerprint, surface.planning_status)
        for surface in before.surface_inventory
    }

def test_function_mapping_is_informational_not_a_security_finding(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    assert http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "public-image",
            "surface_group": "public image",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/upload/logo.png",
            "surface_type": "static_file",
            "source_fact_id": "origin",
        },
    ).status_code == 200
    client = InProcessClient(http_client)
    mapping_project = client.get_project(project_id)
    behavior_key = behavior_identity(mapping_project.surface_inventory[0])[0]
    assert _create_agent_hypothesis_work(
        client,
        mapping_project,
        "reasoner",
        {
            "from": ["origin"],
            "behavior_key": behavior_key,
            "path": "/upload/logo.png",
            "description": "Compatibility mapping for a legacy static observation.",
            "hypothesis": "Record the static resource as an informational observation.",
            "test_family": "surface_config",
            "test_variant": "function_mapping",
            "action_kind": "surface_discovery",
            "confidence": 0.8,
            "impact": 1.0,
            "estimated_cost": 1.0,
            "risk_level": "safe",
        },
    ) is True
    planned = client.get_project(project_id)
    intent = planned.intents[0]
    coverage_id = intent.coverage_refs[0]
    assert http_client.post(
        f"/projects/{project_id}/intents/{intent.id}/heartbeat",
        json={"worker": "executor"},
    ).status_code == 200

    concluded = http_client.post(
        f"/projects/{project_id}/intents/{intent.id}/conclude",
        json={
            "worker": "executor",
            "description": "The static image endpoint was mapped successfully.",
            "status": "confirmed",
            "vuln_type": "function_mapping",
            "severity": "info",
            "coverage_refs": [coverage_id],
        },
    )
    assert concluded.status_code == 200
    fact = concluded.json()["fact"]
    assert fact["status"] is None
    assert fact["vuln_type"] is None
    assert fact["severity"] is None
    assert fact["kind"] == "surface_observation"
    assert fact["result_class"] is None

    detail = http_client.get(f"/projects/{project_id}").json()
    coverage = next(item for item in detail["coverage_items"] if item["id"] == coverage_id)
    assert coverage["outcome"] == "informational"
    assert coverage["variant_results"][0]["status"] == "informational"

    historical = http_client.post(
        f"/projects/{project_id}/facts",
        json={
            "description": "Legacy mapping row",
            "status": "confirmed",
            "vuln_type": "function_mapping",
            "severity": "info",
        },
    )
    assert historical.status_code == 201
    refreshed = http_client.get(f"/projects/{project_id}").json()
    historical_model = next(
        item for item in refreshed["facts"] if item["id"] == historical.json()["id"]
    )
    assert historical_model["result_class"] is None

    assert client.claim_reason(project_id, "reasoner", "test completion").ok
    completed = client.complete(project_id, [], "assessment recorded", "reasoner")
    assert completed.status_code == 200
    assert http_client.get(f"/projects/{project_id}/attack-paths").json() == []



def test_failed_high_priority_behavior_does_not_block_next_breadth_slot(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    endpoint = f"/projects/{project_id}/surfaces"
    for payload in (
        {
            "fingerprint": "admin-post",
            "surface_group": "admin update",
            "target": "example.test",
            "port": 443,
            "method": "POST",
            "path_template": "/admin/update",
            "params": ["id"],
            "auth_context": "admin",
            "surface_type": "admin_route",
            "source_fact_id": "origin",
        },
        {
            "fingerprint": "public-search",
            "surface_group": "public search",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/search",
            "params": ["q"],
            "auth_context": "anonymous",
            "surface_type": "route",
            "source_fact_id": "origin",
        },
    ):
        assert http_client.post(endpoint, json=payload).status_code == 200

    delegate = InProcessClient(http_client)

    class FailFirstClient:
        def __init__(self):
            self.failed = False

        def __getattr__(self, name):
            return getattr(delegate, name)

        def materialize_hypothesis_work(self, project_id: str, **payload):
            if not self.failed:
                self.failed = True
                return ApiResult(status_code=500, text="synthetic first behavior failure")
            return delegate.materialize_hypothesis_work(project_id, **payload)

    client = FailFirstClient()
    created = _ensure_pending_surface_mapping_work(
        client,
        delegate.get_project(project_id),
        "reasoner",
        max_items=1,
    )
    assert created == 1
    refreshed = delegate.get_project(project_id)
    statuses = {
        item.path_template: item.planning_status
        for item in refreshed.surface_inventory
    }
    assert statuses["/admin/update"] == "pending"
    assert statuses["/search"] == "assessed"
    assert len(refreshed.intents) == 1

def test_surface_assessment_is_monotonic_until_behavior_gains_new_semantics(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    endpoint = f"/projects/{project_id}/surfaces"
    base = {
        "fingerprint": "stable-search",
        "surface_group": "search",
        "target": "example.test",
        "port": 443,
        "method": "GET",
        "path_template": "/search",
        "params": ["q"],
        "auth_context": "anonymous",
        "source_fact_id": "origin",
    }

    assert http_client.post(endpoint, json={**base, "planning_status": "assessed"}).status_code == 200
    duplicate = http_client.post(endpoint, json=base)
    assert duplicate.status_code == 200
    assert duplicate.json()["planning_status"] == "assessed"

    changed = http_client.post(endpoint, json={**base, "params": ["q", "callback_url"]})
    assert changed.status_code == 200
    assert changed.json()["planning_status"] == "pending"
    assert changed.json()["params"] == ["callback_url", "q"]


def test_v3_mapping_groups_duplicate_surface_observations_by_behavior(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    endpoint = f"/projects/{project_id}/surfaces"
    common = {
        "surface_group": "article detail",
        "target": "example.test",
        "port": 443,
        "method": "GET",
        "auth_context": "session",
        "source_fact_id": "origin",
    }
    first = http_client.post(
        endpoint,
        json={
            **common,
            "fingerprint": "article-100",
            "path_template": "/article/100",
            "params": ["id"],
        },
    )
    second = http_client.post(
        endpoint,
        json={
            **common,
            "fingerprint": "article-200",
            "path_template": "/article/200",
            "params": ["id", "view"],
        },
    )
    assert first.status_code == second.status_code == 200
    client = InProcessClient(http_client)

    assert _ensure_pending_surface_mapping_work(
        client, client.get_project(project_id), "reasoner", max_items=3,
    ) == 1
    refreshed = client.get_project(project_id)
    assert len(refreshed.intents) == 1
    assert len(refreshed.hypotheses) == 1
    assert {item.planning_status for item in refreshed.surface_inventory} == {"assessed"}


def test_v3_dispatch_graph_uses_compact_behavior_view(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    mapping_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "map the article behavior",
            "creator": "reasoner",
            "action_kind": "function_mapping",
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{mapping_intent['id']}/heartbeat",
        json={"worker": "mapper"},
    ).status_code == 200
    mapped_fact = http_client.post(
        f"/projects/{project_id}/intents/{mapping_intent['id']}/conclude",
        json={"worker": "mapper", "description": "Observed the article route behavior."},
    )
    assert mapped_fact.status_code == 200
    evidence_fact_id = mapped_fact.json()["fact"]["id"]
    endpoint = f"/projects/{project_id}/surfaces"
    common = {
        "surface_group": "article detail",
        "target": "example.test",
        "port": 443,
        "method": "GET",
        "auth_context": "anonymous",
        "source_fact_id": evidence_fact_id,
    }
    for fingerprint, path, params in (
        ("article-a", "/article/100", ["id"]),
        ("article-b", "/article/200", ["id", "q"]),
    ):
        response = http_client.post(
            endpoint,
            json={
                **common,
                "fingerprint": fingerprint,
                "path_template": path,
                "params": params,
            },
        )
        assert response.status_code == 200

    payload = json.loads(format_dispatch_graph(InProcessClient(http_client).get_project(project_id)))
    assert "surfaces" not in payload
    assert len(payload["behaviors"]) == 1
    assert payload["behaviors"][0]["observation_count"] == 2
    assert payload["behaviors"][0]["params"] == ["id", "q"]
    assert payload["behaviors"][0]["index_status"] == "indexed"
    assert payload["behaviors"][0]["coverage_status"] == "open"
    assert "planning_status" not in payload["behaviors"][0]
    assert payload["behavior_coverage"] == {
        **payload["behavior_coverage"],
        "indexed": 1,
        "important_total": 1,
        "closed": 0,
        "open": 1,
        "frontier_count": 1,
    }


def test_v3_behavior_frontier_does_not_close_without_required_coverage_profile(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    mapping_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "map admin behaviors",
            "creator": "reasoner",
            "action_kind": "surface_mapping",
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{mapping_intent['id']}/heartbeat",
        json={"worker": "mapper"},
    ).status_code == 200
    mapped = http_client.post(
        f"/projects/{project_id}/intents/{mapping_intent['id']}/conclude",
        json={"worker": "mapper", "description": "Observed 45 distinct admin handlers."},
    )
    assert mapped.status_code == 200
    evidence_fact_id = mapped.json()["fact"]["id"]

    for index in range(45):
        created = http_client.post(
            f"/projects/{project_id}/surfaces",
            json={
                "fingerprint": f"admin-handler-{index}",
                "surface_group": "admin",
                "target": "example.test",
                "port": 443,
                "method": "POST",
                "path_template": f"/admin/handler-{index:03x}",
                "params": ["record_id"],
                "auth_context": "admin",
                "source_fact_id": evidence_fact_id,
            },
        )
        assert created.status_code == 200

    client = InProcessClient(http_client)
    first = json.loads(format_dispatch_graph(client.get_project(project_id)))
    assert first["behavior_coverage"]["important_total"] == 45
    assert first["behavior_coverage"]["open"] == 45
    assert first["behavior_coverage"]["frontier_count"] == 40
    assert len(first["behaviors"]) == 40
    assert {item["coverage_status"] for item in first["behaviors"]} == {"open"}

    tested_behavior = first["behaviors"][0]
    tested_surface = tested_behavior["surface_refs"][0]
    security_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [evidence_fact_id],
            "description": "test one admin handler",
            "creator": "reasoner",
            "action_kind": "security_test",
            "surface_refs": [tested_surface],
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{security_intent['id']}/heartbeat",
        json={"worker": "tester"},
    ).status_code == 200
    concluded = http_client.post(
        f"/projects/{project_id}/intents/{security_intent['id']}/conclude",
        json={
            "worker": "tester",
            "description": "The assigned handler was tested.",
            "data": {"tested_surface_refs": [tested_surface]},
        },
    )
    assert concluded.status_code == 200

    second = json.loads(format_dispatch_graph(client.get_project(project_id)))
    assert second["behavior_coverage"]["closed"] == 0
    assert second["behavior_coverage"]["open"] == 45
    assert second["behavior_coverage"]["frontier_count"] == 40
    assert tested_behavior["behavior_key"] in {
        item["behavior_key"] for item in second["behaviors"]
    }
    current = next(
        item for item in second["behaviors"]
        if item["behavior_key"] == tested_behavior["behavior_key"]
    )
    assert current["profile_missing"] is True
    assert current["required_coverage_count"] == 0
    assert second["behavior_coverage"]["frontier_revision"] == first["behavior_coverage"]["frontier_revision"]


def test_v3_completion_requires_materialized_behavior_coverage(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    evidence = http_client.post(
        f"/projects/{project_id}/facts",
        json={"description": "Observed the administrator settings handler."},
    )
    assert evidence.status_code == 201
    evidence_fact_id = evidence.json()["id"]
    surface = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "admin-settings",
            "surface_group": "admin settings",
            "target": "example.test",
            "port": 443,
            "method": "POST",
            "path_template": "/admin/settings",
            "params": ["site_name"],
            "auth_context": "admin",
            "source_fact_id": evidence_fact_id,
        },
    ).json()
    _claim_reason(http_client, project_id)
    blocked = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": [], "description": "done", "worker": "reasoner"},
    )
    assert blocked.status_code == 409
    coverage_blockers = [
        item for item in blocked.json()["detail"]["blockers"]
        if item["kind"] == "coverage"
    ]
    assert coverage_blockers
    assert all(item["status"] == "profile_missing" for item in coverage_blockers)
    assert all(surface["id"] in item["related_refs"] for item in coverage_blockers)


def test_v3_web_dispatch_graph_keeps_complete_fact_description(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "inspect one authentication result",
            "creator": "reasoner",
            "action_kind": "auth_probe",
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/heartbeat",
        json={"worker": "explorer"},
    ).status_code == 200
    critical_result = "ADMIN_LOGIN_SUCCEEDED_AND_SESSION_IS_VALID"
    description = ("Authentication execution detail. " * 20) + critical_result
    concluded = http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/conclude",
        json={"worker": "explorer", "description": description},
    )
    assert concluded.status_code == 200
    fact_id = concluded.json()["fact"]["id"]

    project = InProcessClient(http_client).get_project(project_id)
    stored_fact = next(fact for fact in project.facts if fact.id == fact_id)
    assert stored_fact.summary == description[:320]

    web_payload = json.loads(format_dispatch_graph(project))
    web_fact = next(fact for fact in web_payload["facts"] if fact["id"] == fact_id)
    assert web_fact["summary"] == description
    assert critical_result in web_fact["summary"]

    non_web_project = project.model_copy(deep=True)
    non_web_project.project = project.project.model_copy(update={"mode": "ctf"})
    non_web_payload = json.loads(format_dispatch_graph(non_web_project))
    non_web_fact = next(
        fact for fact in non_web_payload["facts"] if fact["id"] == fact_id
    )
    assert non_web_fact["summary"] == description[:320]
    assert critical_result not in non_web_fact["summary"]


def test_web_fact_rules_are_added_without_changing_non_web_prompt(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client)
    project = InProcessClient(http_client).get_project(project_id)
    base_prompt = 'existing explore contract'

    web_prompt = _with_web_fact_output_rules(base_prompt, project)
    assert web_prompt.startswith(base_prompt)
    assert 'Start description with one direct sentence' in web_prompt
    assert 'current task log or execution artifact' in web_prompt
    assert 'separate milestone Facts' in web_prompt
    assert 'authentication artifacts inside the project container' in web_prompt
    assert 'is no_result, never a negative security conclusion' in web_prompt
    assert _with_web_fact_output_rules(base_prompt, project, 'mock') == base_prompt

    non_web_project = project.model_copy(deep=True)
    non_web_project.project = project.project.model_copy(update={'mode': 'ctf'})
    assert _with_web_fact_output_rules(base_prompt, non_web_project) == base_prompt


def test_web_fact_keeps_its_execution_log_as_traceable_evidence(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client)
    surface = http_client.post(
        f'/projects/{project_id}/surfaces',
        json={
            'fingerprint': 'traceable-login',
            'surface_group': 'traceable login',
            'target': 'example.test',
            'port': 443,
            'method': 'POST',
            'path_template': '/login',
            'surface_type': 'form',
            'source_fact_id': 'origin',
        },
    ).json()
    intent = http_client.post(
        f'/projects/{project_id}/intents',
        json={
            'from': ['origin'],
            'description': 'test one authentication outcome',
            'creator': 'reasoner',
            'action_kind': 'security_test',
            'surface_ref': surface['id'],
        },
    ).json()
    intent_id = intent['id']
    claimed = http_client.post(
        f'/projects/{project_id}/intents/{intent_id}/heartbeat',
        json={'worker': 'explorer'},
    )
    assert claimed.status_code == 200

    task_log = http_client.post(
        f'/projects/{project_id}/logs',
        json={
            'task_type': 'explore',
            'intent_id': intent_id,
            'worker_name': 'explorer',
            'phase': 'explore_execute',
            'stdin': 'submit the authorized login request',
            'stdout': 'HTTP 302; Set-Cookie: authenticated-session',
            'stderr': '',
            'return_code': 0,
            'duration_ms': 120,
        },
    ).json()
    task_log_id = task_log['id']
    description = (
        'Administrator login succeeded. The response issued an authenticated '
        'session and redirected to the administration page.'
    )
    concluded = http_client.post(
        f'/projects/{project_id}/intents/{intent_id}/conclude',
        json={
            'worker': 'explorer',
            'description': description,
            'data': {'tested_surface_refs': [surface['id']]},
        },
    )
    assert concluded.status_code == 200
    fact = concluded.json()['fact']
    assert fact['description'] == description
    assert f'task_log:{task_log_id}' in fact['evidence_refs']
    assert task_log_id in fact['task_log_refs']


def test_web_reason_uses_cairn_planning_and_binds_only_unique_surface(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client)
    surface_ids = {}
    for fingerprint, path in (
        ('login-form', '/login'),
        ('search-form', '/search'),
    ):
        response = http_client.post(
            f'/projects/{project_id}/surfaces',
            json={
                'fingerprint': fingerprint,
                'surface_group': fingerprint,
                'target': 'example.test',
                'port': 443,
                'method': 'GET',
                'path_template': path,
                'surface_type': 'form',
                'source_fact_id': 'origin',
            },
        )
        assert response.status_code == 200
        surface_ids[path] = response.json()['id']

    project = InProcessClient(http_client).get_project(project_id)
    security = _bind_matching_surface(
        project,
        {
            'from': ['origin'],
            'description': 'test the login authentication behavior',
            'target': 'example.test',
            'port': 443,
            'path': '/login',
            'action_kind': 'auth_probe',
        },
    )
    assert security['surface_ref'] == surface_ids['/login']

    mapping = _bind_matching_surface(
        project,
        {
            'from': ['origin'],
            'description': 'map the login interaction',
            'path': '/login',
            'action_kind': 'asset_discovery',
        },
    )
    assert 'surface_ref' not in mapping

    capability = _bind_matching_surface(
        project,
        {
            'from': ['origin'],
            'description': 'establish reusable CAPTCHA handling',
            'action_kind': 'authentication_capability',
        },
    )
    assert 'surface_ref' not in capability

    first_signature = _intent_signature_from_data(
        project,
        {
            **security,
            'test_variant': 'session_behavior',
        },
    )
    second_signature = _intent_signature_from_data(
        project,
        {
            **security,
            'surface_ref': surface_ids['/search'],
            'test_variant': 'session_behavior',
        },
    )
    assert first_signature != second_signature

    base_prompt = '2. Otherwise, propose one smallest useful Intent.'
    web_prompt = _with_web_reason_planning_rules(base_prompt, project, 2)
    assert 'propose one or two smallest useful Intents' in web_prompt
    assert 'no more than 2 entries' in web_prompt
    assert 'independent, high-value, non-overlapping' in web_prompt
    assert 'fixed page-by-vulnerability matrix' in web_prompt
    assert 'authenticated/privileged session as a milestone' in web_prompt
    assert 'from that Fact' in web_prompt
    assert _with_web_reason_planning_rules(base_prompt, project, 2, 'mock') == base_prompt

    non_web = project.model_copy(deep=True)
    non_web.project = project.project.model_copy(update={'mode': 'ctf'})
    assert _bind_matching_surface(non_web, security) == security
    assert _with_web_reason_planning_rules(base_prompt, non_web, 2) == base_prompt


def test_surface_graph_state_uses_exact_surface_ref_across_api_ui_and_report(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client)
    mapping_intent = http_client.post(
        f'/projects/{project_id}/intents',
        json={
            'from': ['origin'],
            'description': 'map the login and search pages',
            'creator': 'reasoner',
            'action_kind': 'asset_discovery',
        },
    ).json()
    mapping_intent_id = mapping_intent['id']
    assert http_client.post(
        f'/projects/{project_id}/intents/{mapping_intent_id}/heartbeat',
        json={'worker': 'mapper'},
    ).status_code == 200
    mapped = http_client.post(
        f'/projects/{project_id}/intents/{mapping_intent_id}/conclude',
        json={
            'worker': 'mapper',
            'description': 'The login and search pages were mapped.',
        },
    )
    assert mapped.status_code == 200
    mapping_fact_id = mapped.json()['fact']['id']

    surface_ids = {}
    for fingerprint, path, surface_group in (
        ('login-form', '/login', 'login form'),
        ('search-form', '/search', 'search form'),
    ):
        response = http_client.post(
            f'/projects/{project_id}/surfaces',
            json={
                'fingerprint': fingerprint,
                'surface_group': surface_group,
                'target': 'example.test',
                'port': 443,
                'method': 'GET',
                'path_template': path,
                'surface_type': 'form',
                'source_fact_id': mapping_fact_id,
            },
        )
        assert response.status_code == 200
        surface_ids[path] = response.json()['id']

    security_intent = http_client.post(
        f'/projects/{project_id}/intents',
        json={
            'from': [mapping_fact_id],
            'description': 'test only the login form authentication behavior',
            'creator': 'reasoner',
            'action_kind': 'auth_probe',
            'surface_ref': surface_ids['/login'],
        },
    ).json()
    security_intent_id = security_intent['id']
    assert http_client.post(
        f'/projects/{project_id}/intents/{security_intent_id}/heartbeat',
        json={'worker': 'explorer'},
    ).status_code == 200
    tested = http_client.post(
        f'/projects/{project_id}/intents/{security_intent_id}/conclude',
        json={
            'worker': 'explorer',
            'description': 'The login form authentication behavior was tested.',
            'data': {'tested_surface_refs': [surface_ids['/login']]},
        },
    )
    assert tested.status_code == 200

    for view in ('dispatch', 'full'):
        detail = http_client.get(
            f'/projects/{project_id}?view={view}',
        ).json()
        states = {
            surface['path_template']: (
                surface['graph_discovery_status'],
                surface['graph_testing_status'],
            )
            for surface in detail['surface_inventory']
        }
        assert states == {
            '/login': ('mapped', 'security_tested'),
            '/search': ('mapped', 'not_tested'),
        }

    login_surface_id = surface_ids['/login']
    search_surface_id = surface_ids['/search']
    report = http_client.get(
        f'/projects/{project_id}/export?format=report',
    ).text
    assert (
        f'- {login_surface_id} (GET /login): '
        'graph_state=mapped / security_tested'
    ) in report
    assert (
        f'- {search_surface_id} (GET /search): '
        'graph_state=mapped / not_tested'
    ) in report

    index = http_client.get('/').text
    assert 'surface.required_coverage_count' in index
    assert 'surface.completed_coverage_count' in index
    assert 'surface.test_status' in index
    assert 'surface.graph_testing_status' not in index
    assert 'factIds.includes(intent.to)' not in index

    with get_conn() as conn:
        conn.execute(
            'UPDATE projects SET mode = ? WHERE id = ?',
            ('ctf', project_id),
        )
    non_web = http_client.get(
        f'/projects/{project_id}?view=full',
    ).json()
    assert all(
        surface['graph_discovery_status'] is None
        and surface['graph_testing_status'] is None
        for surface in non_web['surface_inventory']
    )


def test_v2_assesses_non_security_behavior_without_creating_matrix(http_client: TestClient) -> None:
    project_id = _create_real_project(http_client)
    surface = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "about-page",
            "surface_group": "public about page",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/about",
            "params": [],
            "auth_context": "anonymous",
            "source_fact_id": "origin",
        },
    )
    assert surface.status_code == 200
    client = InProcessClient(http_client)
    assert ensure_coverage_work(client, client.get_project(project_id), "reasoner") == 0
    detail = client.get_project(project_id)
    assert detail.surface_inventory[0].planning_status == "assessed"
    assert detail.hypotheses == []
    assert detail.coverage_items == []
    assert detail.intents == []
    assert client.claim_reason(project_id, "reasoner", "test completion").ok
    completed = client.complete(
        project_id, [], "no evidence-supported security hypothesis remained", "reasoner"
    )
    assert completed.status_code == 200


def test_target_aware_default_recon_profiles(http_client: TestClient) -> None:
    ip = http_client.post(
        "/projects",
        json={"title": "ip", "origin": "http://192.0.2.10", "goal": "assess", "mode": "real_website"},
    ).json()["project"]
    api = http_client.post(
        "/projects",
        json={"title": "api", "origin": "https://api.example.test", "goal": "assess", "mode": "real_website"},
    ).json()["project"]
    passive = http_client.post(
        "/projects",
        json={
            "title": "passive",
            "origin": "https://example.test",
            "goal": "assess",
            "mode": "real_website",
            "scope_policy": {"passive_only": True},
        },
    ).json()["project"]

    assert ip["recon_profile"]["target_type"] == "ip"
    assert "subdomain" not in ip["recon_profile"]["required_categories"]
    assert api["recon_profile"]["target_type"] == "api"
    assert "subdomain" not in api["recon_profile"]["required_categories"]

    assert passive["recon_profile"]["required_categories"] == []

def test_behavior_clustering_merges_parameters_but_preserves_auth_boundaries() -> None:
    surfaces = [
        {
            "fingerprint": "search-a", "target": "example.test", "port": 443,
            "method": "GET", "path_template": "/search/123", "params": ["q"],
            "auth_context": "anonymous", "source_fact_id": "f001",
        },
        {
            "fingerprint": "search-b", "target": "example.test", "port": 443,
            "method": "GET", "path_template": "/search/456", "params": ["callback_url"],
            "auth_context": "anonymous", "source_fact_id": "f002",
        },
        {
            "fingerprint": "search-session", "target": "example.test", "port": 443,
            "method": "GET", "path_template": "/search/789", "params": ["account_id"],
            "auth_context": "session", "source_fact_id": "f003",
        },
    ]

    clustered = cluster_behaviors(surfaces)

    assert len(clustered) == 2
    anonymous = next(item for item in clustered if item["auth_context"] == "anonymous")
    assert anonymous["params"] == ["callback_url", "q"]
    assert anonymous["evidence_fact_ids"] == ["f001", "f002"]
    candidates = derive_candidates(surfaces)
    anonymous_candidates = [
        item for item in candidates if item.behavior_key == anonymous["behavior_key"]
    ]
    assert len({item.test_variant for item in anonymous_candidates}) == len(anonymous_candidates)
    assert "ssrf" in {item.test_variant for item in anonymous_candidates}


def test_v3_agent_materializes_only_exact_evidence_backed_hypothesis(http_client: TestClient) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    created_surface = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "search-route",
            "surface_group": "search",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/index.php?r=search",
            "params": ["q"],
            "auth_context": "anonymous",
            "source_fact_id": "origin",
        },
    )
    assert created_surface.status_code == 200
    client = InProcessClient(http_client)
    project = client.get_project(project_id)
    assert project.project.planning_version == 3
    behavior_key = behavior_identity(project.surface_inventory[0])[0]
    decision = {
        "from": ["origin"],
        "description": "Check the observed rendered search input for XSS",
        "behavior_key": behavior_key,
        "hypothesis": "The observed q input may reach a rendered response sink.",
        "test_family": "client_side",
        "test_variant": "xss",
        "expected_evidence": ["controlled marker reflection with executable context"],
        "risk_level": "low",
        "confidence": 0.7,
        "impact": 3,
    }

    assert _create_agent_hypothesis_work(client, project, "reasoner", decision) is True
    refreshed = client.get_project(project_id)
    assert len(refreshed.hypotheses) == 1
    assert len(refreshed.coverage_items) == 1
    assert len(refreshed.intents) == 1
    assert refreshed.hypotheses[0].test_variant == "xss"
    assert refreshed.surface_inventory[0].planning_status == "assessed"
    assert _create_agent_hypothesis_work(client, refreshed, "reasoner", decision) is False
    assert len(client.get_project(project_id).hypotheses) == 1
    intent = refreshed.intents[0]
    coverage_id = refreshed.coverage_items[0].id
    claimed = http_client.post(
        f"/projects/{project_id}/intents/{intent.id}/heartbeat", json={"worker": "executor"}
    )
    assert claimed.status_code == 200
    concluded = http_client.post(
        f"/projects/{project_id}/intents/{intent.id}/conclude",
        json={
            "worker": "executor",
            "description": "The test cannot run while the authorized fixture lacks the required role.",
            "status": "blocked_by_precondition",
            "vuln_type": "xss",
            "coverage_refs": [coverage_id],
            "kind": "precondition",
            "summary": "Required role is unavailable",
            "subject": {"behavior_key": behavior_key},
            "data": {"precondition": "authenticated test role"},
            "parent_fact_ids": ["origin"],
            "confidence": 1.0,
        },
    )
    assert concluded.status_code == 200
    assert client.get_project(project_id).hypotheses[0].status == "concluded"


def test_v3_frontier_prunes_stalled_evidence_basis_and_reopens_for_new_fact(
    http_client: TestClient,
) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    surface_response = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "search-stall",
            "surface_group": "search",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path_template": "/search",
            "params": ["q"],
            "auth_context": "anonymous",
            "source_fact_id": "origin",
            "planning_status": "assessed",
        },
    )
    assert surface_response.status_code == 200
    project = InProcessClient(http_client).get_project(project_id)
    behavior_key = behavior_identity(project.surface_inventory[0])[0]
    for index, variant in enumerate(("xss_reflected", "xss_stored"), start=1):
        response = http_client.post(
            f"/projects/{project_id}/hypotheses",
            json={
                "behavior_key": behavior_key,
                "test_family": "client_side",
                "test_variant": variant,
                "rationale": "No conclusive signal on the current evidence basis.",
                "trigger_fact_ids": ["origin"],
                "confidence": 0.6,
                "impact": 3,
                "goal_value": 1,
                "novelty": 1,
                "estimated_cost": 2,
                "score": 0.9,
                "required": False,
                "status": "inconclusive",
                "basis_fingerprint": f"stalled-{index}",
            },
        )
        assert response.status_code == 201

    candidate = {
        "from": ["origin"],
        "description": "Check one additional reflected rendering variant.",
        "behavior_key": behavior_key,
        "hypothesis": "The query may reach a rendered response sink.",
        "test_family": "client_side",
        "test_variant": "xss_context",
        "expected_evidence": ["controlled marker in an executable context"],
        "risk_level": "medium",
        "confidence": 0.8,
        "impact": 4,
        "estimated_cost": 1,
    }
    stalled = InProcessClient(http_client).get_project(project_id)
    assert _select_v3_frontier(stalled, [candidate], max_items=3) == []

    new_fact = http_client.post(
        f"/projects/{project_id}/facts",
        json={
            "description": "A controlled marker is reflected inside an HTML attribute.",
            "kind": "observation",
            "summary": "New reflected HTML attribute sink",
            "subject": {"behavior_key": behavior_key},
            "data": {"sink": "html_attribute", "marker_reflected": True},
            "parent_fact_ids": ["origin"],
            "confidence": 0.9,
        },
    )
    assert new_fact.status_code == 201
    reopened = InProcessClient(http_client).get_project(project_id)
    selected = _select_v3_frontier(
        reopened,
        [{**candidate, "from": [new_fact.json()["id"]]}],
        max_items=3,
    )
    assert len(selected) == 1


def test_route_selector_values_are_distinct_behaviors() -> None:
    base = {
        "target": "example.test", "port": 443, "method": "GET",
        "params": [], "auth_context": "session", "traits": {},
    }
    manage = behavior_identity({**base, "path_template": "/admin.php?r=manageinfo"})[0]
    create = behavior_identity({**base, "path_template": "/admin.php?r=newwz"})[0]

    assert manage != create
    assert "r=manageinfo" in manage
    assert "r=newwz" in create


def test_destructive_intent_requires_explicit_scope_authorization(http_client: TestClient) -> None:
    project_id = _create_real_project(http_client, planning_version=3)
    response = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "Delete a record",
            "creator": "reasoner",
            "target": "example.test",
            "port": 443,
            "path": "/admin/delete",
            "action_kind": "delete_record",
        },
    )

    assert response.status_code == 400
    assert "destructive" in response.json()["detail"]


def _create_authorized_mutation_project(http_client: TestClient) -> str:
    response = http_client.post(
        "/projects",
        json={
            "title": "authorized mutation state check",
            "origin": "https://example.test/",
            "goal": "assess authorized disposable test data",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "scope_policy": {
                "allowed_targets": ["example.test"],
                "allowed_ports": [443],
                "allow_destructive": True,
                "destructive_action_kinds": ["delete_test_record"],
                "destructive_test_identities": ["test-admin"],
                "destructive_test_data_refs": ["record:test-42"],
                "destructive_forbidden_assets": ["/production/billing"],
                "destructive_state_check_required": True,
                "destructive_recovery_procedure_ref": "runbook:test-data-restore",
            },
            "recon_profile": {"required_categories": []},
        },
    )
    assert response.status_code == 201
    project_id = response.json()["project"]["id"]
    with get_conn() as conn:
        conn.execute(
            "UPDATE projects SET planning_version = 3, phase = 'explore' WHERE id = ?",
            (project_id,),
        )
    return project_id


def _create_high_risk_intent(
    http_client: TestClient,
    project_id: str,
    **overrides,
) -> object:
    payload = {
        "from": ["origin"],
        "description": "Delete the authorized disposable test record once.",
        "creator": "reasoner",
        "target": "example.test",
        "port": 443,
        "path": "/test-records/42",
        "action_kind": "delete_test_record",
        "test_variant": "workflow_invariant",
        "risk_level": "high",
        "test_identity": "test-admin",
        "test_data_refs": ["record:test-42"],
    }
    payload.update(overrides)
    return http_client.post(f"/projects/{project_id}/intents", json=payload)


def test_high_risk_intent_requires_exact_allow_list_authorization(http_client: TestClient) -> None:
    project_id = _create_authorized_mutation_project(http_client)

    allowed = _create_high_risk_intent(http_client, project_id)
    assert allowed.status_code == 201
    assert allowed.json()["risk_level"] == "high"
    assert allowed.json()["test_data_refs"] == ["record:test-42"]

    wrong_action = _create_high_risk_intent(
        http_client, project_id, action_kind="drop_database",
    )
    assert wrong_action.status_code == 400
    wrong_identity = _create_high_risk_intent(
        http_client, project_id, test_identity="production-admin",
    )
    assert wrong_identity.status_code == 400
    missing_data = _create_high_risk_intent(
        http_client, project_id, test_data_refs=[],
    )
    assert missing_data.status_code == 400
    forbidden = _create_high_risk_intent(
        http_client, project_id, path="/production/billing/invoices",
    )
    assert forbidden.status_code == 400

    with get_conn() as conn:
        policy = json.loads(
            conn.execute(
                "SELECT scope_policy FROM projects WHERE id = ?", (project_id,)
            ).fetchone()["scope_policy"]
        )
        policy["destructive_action_kinds"] = []
        conn.execute(
            "UPDATE projects SET scope_policy = ? WHERE id = ?",
            (json.dumps(policy), project_id),
        )
    revoked_claim = http_client.post(
        f"/projects/{project_id}/intents/{allowed.json()['id']}/heartbeat",
        json={"worker": "executor"},
    )
    assert revoked_claim.status_code == 400


def test_uncertain_mutation_is_gated_until_structured_state_check(http_client: TestClient) -> None:
    project_id = _create_authorized_mutation_project(http_client)
    mutation_response = _create_high_risk_intent(http_client, project_id)
    assert mutation_response.status_code == 201
    mutation = mutation_response.json()
    claim_intent(http_client, project_id, mutation["id"])

    failed = http_client.post(
        f"/projects/{project_id}/intents/{mutation['id']}/failure",
        json={
            "worker": "executor",
            "error": "connection lost after submit",
            "max_attempts": 3,
            "backoff_seconds": 0,
        },
    )
    assert failed.status_code == 200
    assert failed.json()["effect_state"] == "unknown"
    assert failed.json()["requires_state_check"] is True

    gated = http_client.post(
        f"/projects/{project_id}/intents/{mutation['id']}/heartbeat",
        json={"worker": "executor"},
    )
    assert gated.status_code == 409

    state_check_response = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": f"Read target state for uncertain mutation {mutation['id']}.",
            "creator": "reasoner",
            "target": mutation["target"],
            "port": mutation["port"],
            "path": mutation["path"],
            "action_kind": "state_check",
            "test_variant": "read_after_uncertain_mutation",
            "risk_level": "standard",
        },
    )
    assert state_check_response.status_code == 201
    state_check = state_check_response.json()
    claim_intent(http_client, project_id, state_check["id"], worker="observer")
    checked = conclude_intent(
        http_client,
        project_id,
        state_check["id"],
        worker="observer",
        description="The disposable test record still exists.",
        data={
            "state_check": {
                "mutation_intent_id": mutation["id"],
                "observed_state": "not_applied",
                "evidence_refs": ["task_log:state-check-1"],
            }
        },
    )
    assert checked["fact"]["data"]["state_check"]["observed_state"] == "not_applied"

    reclaimed = http_client.post(
        f"/projects/{project_id}/intents/{mutation['id']}/heartbeat",
        json={"worker": "executor"},
    )
    assert reclaimed.status_code == 200
