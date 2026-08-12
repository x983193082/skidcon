from __future__ import annotations

import json

from fastapi.testclient import TestClient

from skidc.dispatcher.contracts import extract_reason_handoff, validate_reason_payload
from skidc.dispatcher.models import ReasonCheckpoint
from skidc.dispatcher.prompting import format_coverage_summary
from skidc.dispatcher.tasks.explore import _write_explore_conclusion
from skidc.dispatcher.tasks.reason import (
    _coverage_from_seed_deck,
    _coverage_key,
    _create_coverage_items,
    ensure_coverage_work,
    _persist_reason_handoff,
    _profile_coverage_from_seed,
    _ensure_orphan_verify_work,
)
from tests.conftest import (
    InProcessClient,
    LocalContainerManager,
    create_project,
    dispatch_and_wait,
    make_loop,
    mock_config,
    phase,
)
from tests.support.web_assessment import (
    claim_intent,
    claim_reason,
    conclude_intent,
    create_intent,
    create_real_web_project,
    create_required_coverage,
    create_surface,
)


def test_bootstrap_completes_project_end_to_end(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            reason=phase("complete", zero_outcomes=["intent"]),
            explore=phase("fact"),
        ),
        client,
        containers,
    )
    project_id = create_project(http_client)
    try:
        dispatch_and_wait(loop)
        project = client.get_project(project_id)
    finally:
        loop.close()

    assert project.project.status == "completed"
    # bootstrap conclude wrote f001, then completion intent points at goal
    assert [fact.id for fact in project.facts] == ["origin", "goal", "f001"]
    assert [(i.id, i.to) for i in project.intents] == [("i001", "f001"), ("i002", "goal")]


def test_reason_explore_reason_complete_chain(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            # propose intents until there are >=3 facts, then declare complete
            reason=phase("intent", rules=[{"fact_ids_gte": 3, "force": "complete"}]),
            explore=phase("fact"),
        ),
        client,
        containers,
    )
    project_id = create_project(http_client)
    # seed one concluded fact so the project is past its initial state
    assert client.create_intent(project_id, ["origin"], "seed", "seed-worker").ok
    assert client.heartbeat(project_id, "i001", "seed-worker").ok
    assert client.conclude(project_id, "i001", "seed-worker", "seed fact").ok

    try:
        dispatch_and_wait(loop)  # reason -> creates intent i002
        assert loop.reason_checkpoints[project_id] == ReasonCheckpoint(3, 0, 1)
        dispatch_and_wait(loop)  # explore i002 -> fact f002
        dispatch_and_wait(loop)  # reason sees 4 facts -> complete
        project = client.get_project(project_id)
    finally:
        loop.close()

    assert project.project.status == "completed"
    assert [fact.id for fact in project.facts] == ["origin", "goal", "f001", "f002"]
    assert [(i.id, i.to) for i in project.intents] == [("i001", "f001"), ("i002", "f002"), ("i003", "goal")]
    # the graph snapshot really was injected into the (mock) container for each phase
    assert any("/reason_execute-" in path and "f002" in content for _, path, content in containers.writes)
    assert any("/explore_execute-" in path and "f001" in content for _, path, content in containers.writes)


def test_v3_recon_reason_intent_does_not_materialize_surface_or_coverage(
    http_client: TestClient,
) -> None:
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            reason=phase("intent"),
            explore=phase("fact"),
        ),
        client,
        containers,
    )
    project_id = create_project(
        http_client,
        bootstrap_enabled=False,
        required_recon_categories=["port_scan", "directory", "asset"],
    )
    try:
        dispatch_and_wait(loop)
        project = client.get_project(project_id)
    finally:
        loop.close()

    assert project.project.phase == "recon"
    assert len(project.intents) >= 1
    assert project.surface_inventory == []
    assert project.coverage_items == []


def test_reason_stops_for_attention_when_required_coverage_is_unresolved(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            reason=phase("complete"),
            explore=phase("fact"),
        ),
        client,
        containers,
    )
    project_id = create_project(
        http_client, bootstrap_enabled=False, required_recon_categories=[]
    )
    advanced = http_client.post(f"/projects/{project_id}/phase/advance", json={})
    assert advanced.status_code == 200 and advanced.json()["advanced"]
    coverage = http_client.post(
        f"/projects/{project_id}/coverage",
        json={
            "item_type": "admin_route",
            "path": "/admin.php",
            "description": "Admin login has an unresolved advisory coverage entry.",
            "priority": 9,
        },
    )
    assert coverage.status_code == 201

    try:
        dispatch_and_wait(loop)
        project = http_client.get(f"/projects/{project_id}?view=full").json()
    finally:
        loop.close()

    assert project["project"]["status"] == "completed"
    assert project["project"]["run_state"] == "completed"
    assert project["project"]["completion_outcome"] == "complete"
    assert project["project"]["stop_reason_code"] is None
    assert project["project"]["reason_attempt_count"] == 0
    assert project["project"]["reason_last_error"] is None
    assert project["project"]["completion_blockers"] == []
    assert project["coverage_items"][0]["status"] == "untested"


def test_failed_attempt_fact_can_be_followed_by_alternate_work_with_full_trace(
    http_client: TestClient,
) -> None:
    project_id = create_project(
        http_client, bootstrap_enabled=False, required_recon_categories=[]
    )
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).json()["advanced"]
    coverage = http_client.post(
        f"/projects/{project_id}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "Verify login authentication controls.",
            "surface_group": "auth:/login",
            "test_family": "identity_auth",
            "priority": 8,
        },
    ).json()
    intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "verify login with an alternate method after transient failure",
            "creator": "reasoner",
            "coverage_refs": [coverage["id"]],
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/heartbeat",
        json={"worker": "worker-1"},
    ).status_code == 200
    first_log = http_client.post(
        f"/projects/{project_id}/logs",
        json={
            "task_type": "explore", "intent_id": intent["id"], "worker_name": "worker-1",
            "phase": "explore_execute", "stdin": "first method", "stdout": "",
            "stderr": "timed out", "return_code": 124, "timed_out": True, "duration_ms": 1000,
        },
    ).json()
    retry = http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/failure",
        json={"worker": "worker-1", "error": "first method timed out", "max_attempts": 3, "backoff_seconds": 0},
    ).json()
    assert retry["status"] == "open"
    assert retry["to"] is None
    assert retry["dead_lettered_at"] is None
    assert len(http_client.get(f"/projects/{project_id}").json()["facts"]) == 2

    assert http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/heartbeat",
        json={"worker": "worker-2"},
    ).status_code == 200
    second_log = http_client.post(
        f"/projects/{project_id}/logs",
        json={
            "task_type": "explore", "intent_id": intent["id"], "worker_name": "worker-2",
            "phase": "explore_execute", "stdin": "alternate method",
            "stdout": "security effect reproduced", "stderr": "", "return_code": 0, "duration_ms": 200,
        },
    ).json()
    fact = http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/conclude",
        json={
            "worker": "worker-2",
            "description": "Alternate request sequence reproduced the login security effect.",
            "evidence_refs": ["evidence/login-alternate.txt"],
        },
    ).json()["fact"]
    assert fact["status"] is None and fact["vuln_type"] is None and fact["result_class"] is None
    ledger = http_client.get(f"/projects/{project_id}/coverage").json()[0]
    assert ledger["execution_status"] == "untested"
    assert ledger["outcome"] is None

    verify_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [fact["id"]],
            "description": "independently reproduce the login security effect",
            "creator": "reasoner",
            "action_kind": "verify_candidate",
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{verify_intent['id']}/heartbeat",
        json={"worker": "verifier"},
    ).status_code == 200
    verification = http_client.post(
        f"/projects/{project_id}/intents/{verify_intent['id']}/conclude",
        json={
            "worker": "verifier",
            "description": "A fresh session reproduced the login security effect.",
            "status": "reproduced",
            "verification_of": fact["id"],
            "kind": "verification_result",
            "data": {"result": "reproduced", "attempts": [{"attempt": 1}]},
        },
    ).json()["fact"]
    assert http_client.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": "reasoner", "trigger": "test completion"},
    ).status_code == 200
    completed = http_client.post(
        f"/projects/{project_id}/complete",
        json={"from": [verification["id"]], "description": "goal edge selects the reproduced result", "worker": "reasoner"},
    )
    assert completed.status_code == 200
    paths = http_client.get(f"/projects/{project_id}/attack-paths").json()
    assert len(paths) == 1 and paths[0]["status"] == "complete"
    assert set(paths[0]["task_log_refs"]) == {first_log["id"], second_log["id"]}


def test_enabled_project_skips_bootstrap_when_worker_lacks_capability(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            reason=phase("complete", zero_outcomes=["intent"]),
            explore=phase("fact"),
            task_types=["reason", "explore"],  # no bootstrap capability
        ),
        client,
        containers,
    )
    project_id = create_project(http_client)
    try:
        dispatch_and_wait(loop)  # should go straight to reason -> complete
        project = client.get_project(project_id)
    finally:
        loop.close()

    assert project.project.status == "completed"
    assert [(i.description, i.to) for i in project.intents] == [("mock complete from origin", "goal")]


def test_explore_conclude_fallback_on_timeout(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    # explore_execute is invalid_json -> forces the two-phase conclude fallback,
    # which (default mock behavior) returns a fact and concludes the intent.
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            reason=phase("intent"),
            explore=phase("invalid_json", zero_outcomes=["fact"]),
        ),
        client,
        containers,
    )
    project_id = create_project(http_client, bootstrap_enabled=False)
    try:
        dispatch_and_wait(loop)  # reason proposes an intent
        dispatch_and_wait(loop)  # explore execute returns junk -> conclude fallback writes a fact
        project = client.get_project(project_id)
    finally:
        loop.close()

    fact_ids = [f.id for f in project.facts]
    assert "f001" in fact_ids  # the conclude fallback still produced a fact
    assert any("/explore_conclude-" in path for _, path, _ in containers.writes)


def test_reason_handoff_persists_seed_deck_without_using_it_as_a_second_planner(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    project_id = create_project(http_client, bootstrap_enabled=False)
    payload = {"accepted": True, "data": {
        "recon_complete": True,
        "attack_surface_map": {
            "summary": "Recon found an HTTPS API surface",
            "surfaces": [{"name": "api", "target": "example.test", "port": 443, "surface_type": "web", "evidence": ["origin"]}],
            "admin_routes": ["/admin.php"],
            "upload_points": [{"path": "/upload.php", "description": "Potential file upload endpoint"}],
            "params": [{"path": "/news.php?id=1", "param": "id", "description": "News id parameter"}],
        },
        "explore_seed_deck": {
            "seeds": [
                {
                    "from": ["origin"],
                    "description": "Check API authorization boundaries",
                    "target": "example.test",
                    "port": 443,
                    "surface_type": "web",
                    "action_kind": "authz_probe",
                    "priority": 10,
                    "suggested_tools": ["curl"],
                }
            ],
        },
    }}
    kind, data, _recon_complete = validate_reason_payload(payload, open_intents_empty=True, max_intents=3)

    handoff_fact_ids = _persist_reason_handoff(client, project_id, "reasoner", extract_reason_handoff(payload))
    assert kind == "noop"
    assert data is None

    project = client.get_project(project_id)

    handoff_facts = {fact.goal_type: fact for fact in project.facts if fact.goal_type in {"attack_surface_map", "explore_seed_deck"}}
    assert set(handoff_facts) == {"attack_surface_map", "explore_seed_deck"}
    assert "HTTPS API surface" in handoff_facts["attack_surface_map"].description
    assert project.intents == []

    coverage = {(item.item_type, item.path, item.param): item for item in project.coverage_items}
    assert coverage[("service", None, None)].target == "example.test"
    assert coverage[("service", None, None)].priority == 5
    assert coverage[("admin_route", "/admin.php", None)].priority == 9
    assert coverage[("upload_point", "/upload.php", None)].priority == 10
    assert coverage[("param", "/news.php?id=1", "id")].priority == 7


def test_reason_binds_duplicate_coverage_to_new_intent(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    project_id = create_project(http_client, bootstrap_enabled=False)
    coverage_payload = {
        "item_type": "admin_route",
        "path": "/admin.php",
        "description": "Admin login panel",
        "priority": 9,
    }
    created_coverage = client.create_coverage_item(project_id, **coverage_payload)
    assert created_coverage.ok
    coverage_id = created_coverage.data["id"]
    created_intent = client.create_intent(
        project_id,
        ["origin"],
        "verify admin login",
        "reasoner",
    )
    assert created_intent.ok
    intent_id = created_intent.data["id"]

    _create_coverage_items(
        client,
        project_id,
        "reasoner",
        [{**coverage_payload, "intent_id": intent_id}],
        {_coverage_key(coverage_payload): coverage_id},
    )

    project = client.get_project(project_id)
    assert len(project.coverage_items) == 1
    assert project.coverage_items[0].intent_ids == [intent_id]
    assert project.intents[0].coverage_refs == [coverage_id]


def test_explore_handoff_does_not_expand_coverage_or_handoff_facts(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    project_id = create_project(http_client, bootstrap_enabled=False)
    handoff = {
        "attack_surface_map": {
            "routes": [{"url": "http://example.test/admin.php", "params": ["id"]}],
        },
        "explore_seed_deck": [
            {"from": ["origin"], "description": "duplicate explore handoff"},
        ],
    }

    result = _persist_reason_handoff(
        client,
        project_id,
        "reasoner",
        handoff,
        {},
        real_website=True,
        materialize_coverage=False,
    )
    project = client.get_project(project_id)

    assert result == {}
    assert [fact.id for fact in project.facts] == ["origin", "goal"]
    assert project.coverage_items == []
    assert project.surface_inventory == []

def test_real_website_handoff_builds_medium_grain_coverage_profile(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    project_id = create_project(http_client, bootstrap_enabled=False)
    handoff = {
        "attack_surface_map": {
            "routes": [
                {"url": "http://al.xhcms/xhcms/index.php?id=1"},
                {"url": "http://al.xhcms/xhcms/admin/login.php", "method": "POST", "params": ["username", "password"]},
            ],
            "forms": [
                {"url": "http://al.xhcms/xhcms/contact.php", "method": "POST", "fields": ["name", "mail", "message"]},
            ],
            "upload_points": [
                {"url": "http://al.xhcms/xhcms/admin/upload.php", "method": "POST", "params": ["file"]},
            ],
            "services": [{"target": "al.xhcms", "port": 3306, "type": "database"}],
        },
        "explore_seed_deck": [],
    }
    coverage_index: dict[tuple, str] = {}

    _persist_reason_handoff(
        client,
        project_id,
        "reasoner",
        handoff,
        coverage_index,
        real_website=True,
        support_ports=[3306],
    )
    first = client.get_project(project_id)
    _persist_reason_handoff(
        client,
        project_id,
        "reasoner",
        handoff,
        coverage_index,
        real_website=True,
        support_ports=[3306],
    )
    second = client.get_project(project_id)

    assert len(first.surface_inventory) == 5
    assert 15 <= len(first.coverage_items) <= 35
    config_items = [item for item in first.coverage_items if item.test_family == "surface_config"]
    assert len(config_items) == 4
    assert config_items[0].required is False
    assert len(second.surface_inventory) == len(first.surface_inventory)
    assert len(second.coverage_items) == len(first.coverage_items)
    families = {item.test_family for item in first.coverage_items}
    assert {"surface_config", "identity_auth", "injection", "file_path", "client_side", "support_service"} <= families
    assert "crypto_transport" not in families
    support = [item for item in first.coverage_items if item.test_family == "support_service"]
    assert len(support) == 1
    assert support[0].required is False
    assert support[0].port == 3306
    assert any(item.test_family == "file_path" and item.priority == 10 for item in first.coverage_items)
    summary = json.loads(format_coverage_summary(first))
    assert len(summary["top_unresolved"]) <= 10
    assert "support_service" in summary["by_test_family"]

    intent = client.create_intent(
        project_id,
        ["origin"],
        "Test authentication bypass and SQL injection on the admin login.",
        "reasoner",
        target="al.xhcms",
        port=80,
        surface_type="form",
        action_kind="auth and sqli probe",
    ).data
    assert isinstance(intent, dict)
    seed_items = _profile_coverage_from_seed(
        client,
        project_id,
        {
            "description": "Test authentication bypass and SQL injection on the admin login.",
            "target": "al.xhcms",
            "port": 80,
            "path": "/xhcms/admin/login.php",
            "method": "POST",
            "params": ["username", "password"],
            "surface_type": "form",
            "action_kind": "auth and sqli probe",
        },
        support_ports=[3306],
        source_fact_id=None,
        intent_id=intent["id"],
    )
    _create_coverage_items(client, project_id, "reasoner", seed_items, coverage_index)
    refreshed = client.get_project(project_id)
    bound_families = {
        item.test_family for item in refreshed.coverage_items if intent["id"] in item.intent_ids
    }
    assert bound_families == {"identity_auth"}


def test_v2_does_not_expand_manual_coverage_variants(http_client: TestClient) -> None:
    client = InProcessClient(http_client)
    response = http_client.post(
        "/projects",
        json={
            "title": "finite baseline",
            "origin": "https://example.test/",
            "goal": "assess",
            "mode": "real_website",
        },
    )
    project_id = response.json()["project"]["id"]
    coverage = http_client.post(
        f"/projects/{project_id}/coverage",
        json={
            "item_type": "vuln_class",
            "target": "example.test",
            "port": 443,
            "method": "GET",
            "path": "/search",
            "description": "Search input checks",
            "surface_group": "web:/search",
            "test_family": "injection",
            "test_variants": ["sql", "command"],
            "priority": 7,
            "execution_status": "completed",
            "outcome": "vulnerable",
        },
    ).json()

    before = client.get_project(project_id)
    variants = {item.variant: item.status for item in before.coverage_items[0].variant_results}
    assert variants == {"sql": "untested", "command": "untested"}

    assert ensure_coverage_work(client, before, "reasoner") == 0
    after = client.get_project(project_id)
    assert after.intents == []
    assert after.coverage_items[0].id == coverage["id"]

def _create_web_verify_case(http_client: TestClient) -> tuple[str, str, str]:
    created = http_client.post(
        "/projects",
        json={
            "title": "bounded Verify integration",
            "origin": "http://example.test/",
            "goal": "Assess the authorized local Web application.",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "recon_profile": {"required_categories": []},
        },
    )
    assert created.status_code == 201
    project_id = created.json()["project"]["id"]
    advanced = http_client.post(f"/projects/{project_id}/phase/advance", json={})
    assert advanced.status_code == 200
    assert advanced.json()["advanced"] is True

    candidate_intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "Probe the reflected input and record the observed behavior.",
            "creator": "reasoner",
            "action_kind": "xss_probe",
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{candidate_intent['id']}/heartbeat",
        json={"worker": "explorer"},
    ).status_code == 200
    candidate_response = http_client.post(
        f"/projects/{project_id}/intents/{candidate_intent['id']}/conclude",
        json={
            "worker": "explorer",
            "description": "A reflected marker was observed and requires independent reproduction.",
        },
    )
    assert candidate_response.status_code == 200
    candidate_id = candidate_response.json()["fact"]["id"]

    verify_response = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [candidate_id],
            "description": "Independently reproduce the candidate reflected-input finding.",
            "creator": "reasoner",
            "action_kind": "verify_candidate",
            "priority": 10,
        },
    )
    assert verify_response.status_code == 201
    duplicate = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": [candidate_id],
            "description": "Same Verify work expressed with alternate wording.",
            "creator": "reasoner",
            "action_kind": "verify_candidate",
            "priority": 9,
        },
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == verify_response.json()["id"]
    return project_id, candidate_id, verify_response.json()["id"]


def test_web_explore_candidate_deterministically_creates_verify_intent(
    http_client: TestClient,
) -> None:
    client = InProcessClient(http_client)
    created = http_client.post(
        "/projects",
        json={
            "title": "deterministic Verify handoff",
            "origin": "http://example.test/",
            "goal": "Assess the authorized local Web application.",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "recon_profile": {"required_categories": []},
        },
    )
    project_id = created.json()["project"]["id"]
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).status_code == 200
    surface = http_client.post(
        f"/projects/{project_id}/surfaces",
        json={
            "fingerprint": "search-get-q",
            "surface_group": "search",
            "target": "example.test",
            "port": 80,
            "method": "GET",
            "path_template": "/search",
            "params": ["q"],
            "auth_context": "anonymous",
            "surface_type": "route",
            "source_fact_id": "origin",
        },
    ).json()
    created_intent = client.create_intent(
        project_id,
        ["origin"],
        "Probe one reflected input.",
        "reasoner",
        target="example.test",
        port=80,
        path="/search",
        surface_ref=surface["id"],
        surface_refs=[surface["id"]],
        action_kind="security_test",
        test_variant="xss",
    )
    intent_id = created_intent.data["id"]
    config = mock_config(
        bootstrap=phase("complete"),
        reason=phase("complete"),
        explore=phase("fact"),
    )
    worker = config.workers[0]
    assert client.heartbeat(project_id, intent_id, worker.name).ok
    project = client.get_project(project_id)
    intent = next(item for item in project.intents if item.id == intent_id)

    status = _write_explore_conclusion(
        client,
        project,
        intent,
        worker,
        {
            "description": "The tested marker was reflected in an executable response context.",
            "tested_surface_refs": [surface["id"]],
            "verify_requests": [{
                "claim": "Repeat the request in a fresh session and confirm marker execution.",
                "surface_refs": [surface["id"]],
                "evidence_refs": ["log001"],
            }],
        },
        source="test",
        phase_ms=1,
    )
    assert status == "success"

    after = client.get_project(project_id)
    candidate = next(fact for fact in after.facts if fact.id not in {"origin", "goal"})
    assert candidate.data == {
        "tested_surface_refs": [surface["id"]],
        "verify_requests": [{
            "claim": "Repeat the request in a fresh session and confirm marker execution.",
            "surface_refs": [surface["id"]],
            "evidence_refs": ["log001"],
        }],
        "verify_request": "Repeat the request in a fresh session and confirm marker execution.",
    }
    verify = next(item for item in after.intents if item.action_kind == "verify")
    assert verify.from_ == [candidate.id]
    assert verify.path == "/search"
    assert verify.test_variant == "xss"
    assert verify.surface_refs == [surface["id"]]


def test_web_surface_testing_state_uses_exact_tested_refs(http_client: TestClient) -> None:
    created = http_client.post(
        "/projects",
        json={
            "title": "exact Surface test state",
            "origin": "http://example.test/",
            "goal": "Assess the authorized local Web application.",
            "mode": "real_website",
            "bootstrap_enabled": False,
            "recon_profile": {"required_categories": []},
        },
    ).json()
    project_id = created["project"]["id"]
    assert http_client.post(f"/projects/{project_id}/phase/advance", json={}).status_code == 200
    surfaces = []
    for index in range(2):
        surfaces.append(http_client.post(
            f"/projects/{project_id}/surfaces",
            json={
                "fingerprint": f"route-{index}",
                "surface_group": "routes",
                "target": "example.test",
                "port": 80,
                "method": "GET",
                "path_template": f"/route/{index}",
                "params": [],
                "auth_context": "anonymous",
                "surface_type": "route",
                "source_fact_id": "origin",
            },
        ).json())
    refs = [surface["id"] for surface in surfaces]
    intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "Test the related route batch.",
            "creator": "reasoner",
            "action_kind": "security_test",
            "surface_refs": refs,
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/heartbeat",
        json={"worker": "explorer"},
    ).status_code == 200
    concluded = http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/conclude",
        json={
            "worker": "explorer",
            "description": "Only the first assigned route was actually tested.",
            "data": {"tested_surface_refs": [refs[0]]},
        },
    )
    assert concluded.status_code == 200
    state = {
        surface["id"]: surface["graph_testing_status"]
        for surface in http_client.get(f"/projects/{project_id}").json()["surface_inventory"]
    }
    assert state == {refs[0]: "security_tested", refs[1]: "not_tested"}


def test_reason_restores_orphan_verify_handoff_once(http_client: TestClient) -> None:
    project_id, candidate_id, verify_intent_id = _create_web_verify_case(http_client)
    # Remove only the queued test Intent to simulate a transient handoff failure.
    from skidc.server.db import get_conn

    with get_conn() as conn:
        conn.execute(
            "DELETE FROM intent_sources WHERE project_id = ? AND intent_id = ?",
            (project_id, verify_intent_id),
        )
        conn.execute(
            "DELETE FROM intents WHERE project_id = ? AND id = ?",
            (project_id, verify_intent_id),
        )
        conn.execute(
            "UPDATE facts SET data = ? WHERE project_id = ? AND id = ?",
            (
                json.dumps({"verify_request": "Reproduce the reflected-input candidate."}),
                project_id,
                candidate_id,
            ),
        )

    client = InProcessClient(http_client)
    assert _ensure_orphan_verify_work(client, client.get_project(project_id), "reasoner") == 1
    assert _ensure_orphan_verify_work(client, client.get_project(project_id), "reasoner") == 0


def test_verify_reproduced_runs_all_three_fresh_attempts(
    http_client: TestClient,
) -> None:
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            reason=phase("complete"),
            explore=phase("fact"),
            verify=phase("reproduced"),
        ),
        client,
        containers,
    )
    project_id, candidate_id, verify_intent_id = _create_web_verify_case(http_client)
    try:
        dispatch_and_wait(loop)
        project = client.get_project(project_id)
    finally:
        loop.close()

    result = next(fact for fact in project.facts if fact.verification_of == candidate_id)
    assert result.kind == "verification_result"
    assert result.status == "reproduced"
    assert result.vuln_type is None and result.severity is None
    assert result.data["result"] == "reproduced"
    assert len(result.data["attempts"]) == 3
    logs = http_client.get(
        f"/projects/{project_id}/logs",
        params={"task_type": "verify", "intent_id": verify_intent_id},
    ).json()
    assert {log["phase"] for log in logs} == {
        "verify_execute_attempt_1",
        "verify_execute_attempt_2",
        "verify_execute_attempt_3",
    }


def test_verify_not_reproduced_uses_three_attempts_and_does_not_block_complete(
    http_client: TestClient,
) -> None:
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            reason=phase("complete"),
            explore=phase("fact"),
            verify=phase("not_reproduced"),
        ),
        client,
        containers,
    )
    project_id, candidate_id, verify_intent_id = _create_web_verify_case(http_client)
    try:
        dispatch_and_wait(loop)
        after_verify = client.get_project(project_id)
        result = next(fact for fact in after_verify.facts if fact.verification_of == candidate_id)
        assert result.status == "not_reproduced"
        assert len(result.data["attempts"]) == 3

        dispatch_and_wait(loop)
        completed = client.get_project(project_id)
    finally:
        loop.close()

    assert completed.project.status == "completed"
    logs = http_client.get(
        f"/projects/{project_id}/logs",
        params={"task_type": "verify", "intent_id": verify_intent_id},
    ).json()
    assert {log["phase"] for log in logs} == {
        "verify_execute_attempt_1",
        "verify_execute_attempt_2",
        "verify_execute_attempt_3",
    }
    paths = http_client.get(f"/projects/{project_id}/attack-paths").json()
    assert all(result.id not in path["fact_chain"] for path in paths)


def _create_mock_real_web_project(
    http_client: TestClient,
) -> tuple[str, dict, list[str]]:
    project_id = create_real_web_project(http_client)
    surface = create_surface(
        http_client, project_id, fingerprint="surface-session", method="GET",
        path="/session", params=[], surface_type="route", traits={"auth": True},
    )
    coverage_ids = [
        create_required_coverage(
            http_client, project_id, surface, family=family, variant=variant,
        )["id"]
        for family, variant in (
            ("identity_auth", "authentication_flow"),
            ("session_csrf", "csrf_state_change"),
        )
    ]
    return project_id, surface, coverage_ids


def _reason_complete(
    http_client: TestClient,
    project_id: str,
    *,
    from_ids: list[str],
):
    claim_reason(http_client, project_id)
    response = http_client.post(
        f"/projects/{project_id}/complete",
        json={
            "from": from_ids,
            "description": "All required assessment work has terminal evidence.",
            "worker": "reasoner",
        },
    )
    if response.status_code != 200:
        released = http_client.post(
            f"/projects/{project_id}/reason/release",
            json={"worker": "reasoner"},
        )
        assert released.status_code == 200
    return response


def _conclude_all_required_mock_coverage(
    http_client: TestClient,
    project_id: str,
    surface: dict,
    coverage_ids: list[str],
) -> tuple[str, str]:
    first = create_intent(
        http_client, project_id, surface=surface,
        coverage_ids=[coverage_ids[0]], test_variant="authentication_flow",
    )
    claim_intent(http_client, project_id, first["id"])
    candidate = conclude_intent(
        http_client, project_id, first["id"],
        description="Candidate authentication impact requires Verify.",
        data={
            "tested_surface_refs": [surface["id"]],
            "verify_request": "Reproduce candidate authentication impact.",
            "verify_requests": [{
                "claim": "Reproduce candidate authentication impact.",
                "surface_refs": [surface["id"]],
                "evidence_refs": [],
            }],
        },
    )["fact"]
    verify = create_intent(
        http_client, project_id, surface=surface,
        coverage_ids=[coverage_ids[0]], action_kind="verify",
        test_variant="authentication_flow", from_ids=[candidate["id"]],
    )

    second = create_intent(
        http_client, project_id, surface=surface,
        coverage_ids=[coverage_ids[1]], test_variant="csrf_state_change",
    )
    claim_intent(http_client, project_id, second["id"])
    conclude_intent(
        http_client, project_id, second["id"],
        description="CSRF controls rejected the tested cross-origin requests.",
        data={"tested_surface_refs": [surface["id"]]},
    )
    return candidate["id"], verify["id"]


def _mock_web_loop(http_client: TestClient, *, verify_result: str):
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"), reason=phase("complete"),
            explore=phase("fact"), verify=phase(verify_result),
        ),
        client,
        containers,
    )
    return client, containers, loop


def _run_required_coverage_and_verify(
    http_client: TestClient,
    *,
    verify_result: str,
):
    project_id, surface, coverage_ids = _create_mock_real_web_project(http_client)
    premature = _reason_complete(http_client, project_id, from_ids=[])
    assert premature.status_code == 409
    candidate_id, verify_intent_id = _conclude_all_required_mock_coverage(
        http_client, project_id, surface, coverage_ids,
    )
    client, _containers, loop = _mock_web_loop(
        http_client, verify_result=verify_result,
    )
    try:
        dispatch_and_wait(loop)
        after_verify = client.get_project(project_id)
        verification = next(
            fact for fact in after_verify.facts
            if fact.verification_of == candidate_id
        )
        assert verification.status == verify_result
        assert len(verification.data["attempts"]) == 3
        dispatch_and_wait(loop)
        completed = client.get_project(project_id)
    finally:
        loop.close()
    return completed, verification, verify_intent_id


def test_web_assessment_completes_only_after_all_required_coverage_and_verify(
    http_client: TestClient,
) -> None:
    completed, verification, _verify_intent_id = _run_required_coverage_and_verify(
        http_client, verify_result="reproduced",
    )
    assert verification.status == "reproduced"
    assert completed.project.status == "completed"
    assert completed.project.completion_blockers == []


def test_zero_finding_web_assessment_completes_with_empty_completion_sources(
    http_client: TestClient,
) -> None:
    completed, verification, _verify_intent_id = _run_required_coverage_and_verify(
        http_client, verify_result="not_reproduced",
    )
    assert verification.status == "not_reproduced"
    assert completed.project.status == "completed"
    completion = next(intent for intent in completed.intents if intent.to == "goal")
    assert completion.from_ == []
