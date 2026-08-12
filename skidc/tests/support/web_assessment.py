from __future__ import annotations

from fastapi.testclient import TestClient

from skidc.server.db import get_conn


def create_real_web_project(http: TestClient, *, planning_version: int = 3) -> str:
    response = http.post(
        "/projects",
        json={
            "title": "evidence-backed web assessment",
            "origin": "https://example.test/",
            "goal": "assess the authorized target",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "scope_policy": {
                "allowed_targets": ["example.test"],
                "allowed_ports": [443],
            },
            "recon_profile": {
                "required_categories": [],
                "optional_categories": [],
                "disabled_categories": ["port_scan", "subdomain", "directory", "asset"],
            },
        },
    )
    assert response.status_code == 201
    project_id = response.json()["project"]["id"]
    with get_conn() as conn:
        conn.execute(
            "UPDATE projects SET planning_version = ?, phase = 'explore' WHERE id = ?",
            (planning_version, project_id),
        )
    return project_id


def create_surface(
    http: TestClient,
    project_id: str,
    *,
    fingerprint: str = "surface-login",
    method: str = "POST",
    path: str = "/login",
    auth_context: str = "anonymous",
    params: list[str] | None = None,
    surface_type: str = "form",
    traits: dict | None = None,
    source_fact_id: str | None = None,
) -> dict:
    if source_fact_id is None:
        fact = http.post(
            f"/projects/{project_id}/facts",
            json={
                "description": f"Observed {method} {path} during authorized mapping.",
                "kind": "surface_observation",
                "status": "completed",
            },
        )
        assert fact.status_code == 201
        source_fact_id = fact.json()["id"]
    response = http.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": fingerprint,
            "surface_group": f"web:{path}",
            "target": "example.test",
            "port": 443,
            "method": method,
            "path_template": path,
            "params": ["username", "password"] if params is None else params,
            "surface_type": surface_type,
            "auth_context": auth_context,
            "traits": traits or {"auth": True, "has_input": True, "writes": True},
            "source_fact_id": source_fact_id,
        },
    )
    assert response.status_code in {200, 201}
    return response.json()


def create_required_coverage(
    http: TestClient,
    project_id: str,
    surface: dict,
    *,
    family: str,
    variant: str,
) -> dict:
    response = http.post(
        f"/projects/{project_id}/coverage",
        json={
            "item_type": "vuln_class",
            "target": surface["target"],
            "port": surface["port"],
            "method": surface["method"],
            "path": surface["path_template"],
            "description": f"{surface['surface_group']} x {family}",
            "surface_group": surface["surface_group"],
            "surface_fingerprint": surface["fingerprint"],
            "test_family": family,
            "test_variants": [variant],
            "auth_context": surface["auth_context"],
            "required": True,
            "priority": 8,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_intent(
    http: TestClient,
    project_id: str,
    *,
    surface: dict,
    coverage_ids: list[str],
    action_kind: str = "security_test",
    test_variant: str = "authentication_flow",
    from_ids: list[str] | None = None,
) -> dict:
    response = http.post(
        f"/projects/{project_id}/intents",
        json={
            "from": from_ids or ["origin"],
            "description": f"Run {test_variant} on {surface['path_template']}",
            "creator": "reasoner",
            "target": surface["target"],
            "port": surface["port"],
            "path": surface["path_template"],
            "surface_type": surface["surface_type"],
            "surface_ref": surface["id"],
            "surface_refs": [surface["id"]],
            "action_kind": action_kind,
            "test_variant": test_variant,
            "coverage_refs": coverage_ids,
            "priority": 8,
        },
    )
    assert response.status_code == 201
    return response.json()


def claim_intent(
    http: TestClient,
    project_id: str,
    intent_id: str,
    worker: str = "executor",
) -> None:
    response = http.post(
        f"/projects/{project_id}/intents/{intent_id}/heartbeat",
        json={"worker": worker},
    )
    assert response.status_code == 200


def conclude_intent(
    http: TestClient,
    project_id: str,
    intent_id: str,
    *,
    description: str,
    worker: str = "executor",
    **fields,
) -> dict:
    response = http.post(
        f"/projects/{project_id}/intents/{intent_id}/conclude",
        json={"worker": worker, "description": description, **fields},
    )
    assert response.status_code == 200, response.text
    return response.json()


def coverage_by_id(http: TestClient, project_id: str, coverage_id: str) -> dict:
    return next(
        item
        for item in http.get(f"/projects/{project_id}/coverage").json()
        if item["id"] == coverage_id
    )


def claim_reason(http: TestClient, project_id: str, worker: str = "reasoner") -> None:
    response = http.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": worker, "trigger": "test completion decision"},
    )
    assert response.status_code == 200
