from __future__ import annotations

import copy
import json

import pytest

from skidc.dispatcher.contracts import validate_reason_payload
from skidc.server.models import ProjectDetail
from tests.conftest import mock_config, phase


def _config():
    return mock_config(bootstrap=phase("complete"), reason=phase("intent"), explore=phase("fact"))


def _create(http, mode="ctf", **extra):
    response = http.post("/projects", json={
        "title": "isolation", "origin": "https://challenge.test", "goal": "solve",
        "mode": mode, **extra,
    })
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("extra", [{}, {"bootstrap_enabled": False}, {"mode": None}])
def test_creation_requires_explicit_mode(http_client, extra):
    response = http_client.post("/projects", json={"title": "t", "origin": "o", "goal": "g", **extra})
    assert response.status_code == 422
    assert http_client.get("/projects").json() == []


def test_ctf_can_disable_bootstrap_without_changing_mode(http_client):
    project = _create(http_client, bootstrap_enabled=False)["project"]
    assert (project["mode"], project["bootstrap_enabled"], project["phase"]) == ("ctf", False, "explore")


def test_web_never_enables_ctf_bootstrap(http_client):
    project = _create(http_client, "real_website", bootstrap_enabled=True)["project"]
    assert (project["mode"], project["bootstrap_enabled"], project["phase"]) == ("real_website", False, "recon")


@pytest.mark.parametrize("mode,target", [("ctf", "real_website"), ("real_website", "ctf"), ("ctf", "ctf")])
@pytest.mark.parametrize("status", ["active", "stopped"])
def test_project_mode_is_immutable_without_state_changes(http_client, mode, target, status):
    pid = _create(http_client, mode)["project"]["id"]
    if status == "stopped":
        assert http_client.put(f"/projects/{pid}/status", json={"status": status}).status_code == 200
    before = http_client.get(f"/projects/{pid}").json()
    response = http_client.put(f"/projects/{pid}/mode", json={"mode": target})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "project_mode_immutable"
    assert http_client.get(f"/projects/{pid}").json() == before


def test_mode_routes_ctf_to_its_own_prompt_bundle():
    config = _config()
    config.runtime.prompt_group = "default"
    routed = config.for_project("ctf", "domain")
    assert routed.runtime.prompt_group == "ctf"
    assert routed.android_bridge is None
    assert config.runtime.prompt_group == "default"
    assert config.for_project("real_website", "domain").runtime.prompt_group == "default"


def test_ctf_cannot_borrow_android_or_web_prompt_bundle():
    config = _config()
    with pytest.raises(ValueError, match="CTF.*Android"):
        config.for_project("ctf", "android")
    config.runtime.prompt_group = "ctf"
    with pytest.raises(ValueError, match="CTF"):
        config.for_project("real_website", "domain")


def test_ctf_routing_drops_android_metadata_from_previously_bound_config():
    config = _config()
    config.workers[0].env.update({"ANDROID_MCP_URL": "http://bridge", "ANDROID_MCP_TOKEN_FILE": "/run/token"})
    config.common_env["ANDROID_MCP_URL"] = "http://bridge"
    routed = config.for_project("ctf", "domain")
    assert not any(key.startswith("ANDROID_MCP_") for key in routed.workers[0].env)
    assert not any(key.startswith("ANDROID_MCP_") for key in routed.common_env)
    assert "ANDROID_MCP_URL" in config.workers[0].env


def test_ctf_cannot_enter_verify_task(http_client):
    from skidc.dispatcher.tasks.verify import run_verify_task
    from skidc.dispatcher.runtime.cancellation import TaskCancellation

    project = ProjectDetail.model_validate(_create(http_client))
    with pytest.raises(ValueError, match="Web"):
        run_verify_task(_config(), object(), object(), project, "", object(), _config().workers[0], TaskCancellation())


def test_ctf_prompt_bundle_is_complete():
    from skidc.dispatcher.config import validate_prompt_resources

    validate_prompt_resources("ctf")


def test_ctf_blackboard_omits_web_metadata_but_preserves_fact_text(http_client):
    from skidc.dispatcher.prompting import format_ctf_graph

    project = ProjectDetail.model_validate(_create(http_client))
    project.project.phase = "recon"  # polluted historical metadata must not become CTF instructions
    project.facts[0].description = "Coverage is a word in the challenge; keep this observation."
    project.facts[0].coverage_refs = ["web-only"]
    project.facts[0].severity = "critical"
    project.facts[0].data = {"verify_request": "Web-only instruction"}
    graph = json.loads(format_ctf_graph(project))
    assert set(graph) == {"project", "facts", "intents", "hints"}
    assert graph["project"]["mode"] == "ctf"
    assert "phase" not in graph["project"]
    assert graph["facts"][0] == {"id": "origin", "description": project.facts[0].description, "evidence_refs": []}


@pytest.mark.parametrize("data", [
    {"recon_complete": True},
    {"intents": [{"from": ["origin"], "description": "x", "action_kind": "verify"}]},
    {"complete": {"from": [], "description": "done"}},
    {"complete": {"from": ["goal"], "description": "done"}},
    {"complete": {"from": ["origin"], "description": "done"}, "intents": []},
    {"intents": [{"from": "origin", "description": "x"}]},
    {"intents": [{"from": ["origin"], "description": " "}]},
    {},
    {"intents": []},
])
def test_ctf_reason_rejects_web_or_invalid_decisions(data):
    from skidc.dispatcher.ctf_contracts import validate_ctf_reason_payload

    with pytest.raises(ValueError):
        validate_ctf_reason_payload({"accepted": True, "data": data}, open_intents_empty=True, max_intents=2)


def test_ctf_reason_accepts_plain_intent_without_mutating_input():
    from skidc.dispatcher.ctf_contracts import validate_ctf_reason_payload

    payload = {"accepted": True, "data": {"intents": [{"from": ["origin"], "description": "Study Coverage in the supplied file"}]}}
    before = copy.deepcopy(payload)
    assert validate_ctf_reason_payload(payload, open_intents_empty=True, max_intents=2) == (
        "intents", payload["data"]["intents"], False,
    )
    assert payload == before


@pytest.mark.parametrize("accepted", [1, "true", None])
def test_ctf_contract_does_not_coerce_accepted(accepted):
    from skidc.dispatcher.ctf_contracts import validate_ctf_explore_payload

    with pytest.raises(ValueError):
        validate_ctf_explore_payload({"accepted": accepted, "data": {"description": "observed"}})


@pytest.mark.parametrize("extra", [{"coverage_refs": []}, {"observed_surfaces": []}, {"verify": "claim"}, {"severity": "high"}])
def test_ctf_explore_rejects_web_fields(extra):
    from skidc.dispatcher.ctf_contracts import validate_ctf_explore_payload

    with pytest.raises(ValueError):
        validate_ctf_explore_payload({"accepted": True, "data": {"description": "observed", **extra}})


def test_ctf_explore_preserves_objective_evidence():
    from skidc.dispatcher.ctf_contracts import validate_ctf_explore_payload

    assert validate_ctf_explore_payload({"accepted": True, "data": {"description": " observed ", "evidence_refs": ["artifact-1"]}}) == (
        "fact", {"description": "observed", "evidence_refs": ["artifact-1"]},
    )


def test_ctf_bootstrap_rejects_web_fields_in_execute_and_conclude():
    from skidc.dispatcher.ctf_contracts import validate_ctf_bootstrap_execute_payload, validate_ctf_bootstrap_conclude_payload

    for validate, data in [
        (validate_ctf_bootstrap_execute_payload, {"fact": {"description": "f", "severity": "high"}, "complete": {"description": "g"}}),
        (validate_ctf_bootstrap_conclude_payload, {"fact": {"description": "f"}, "complete": {"description": "g"}}),
    ]:
        with pytest.raises(ValueError):
            validate({"accepted": True, "data": data})


def test_web_reason_still_accepts_its_surface_contract():
    payload = {"accepted": True, "data": {"intent": {"from": ["origin"], "description": "map", "action_kind": "surface_mapping"}}}
    kind, intents, _ = validate_reason_payload(payload, True, 2, web_mode=True)
    assert kind == "intents"
    assert intents[0]["action_kind"] == "surface_mapping"


def test_ctf_without_bootstrap_runs_blackboard_chain_without_web_state(http_client):
    from tests.conftest import InProcessClient, LocalContainerManager, make_loop, dispatch_and_wait

    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    config = mock_config(
        bootstrap=phase("complete"),
        reason=phase("intent", rules=[{"fact_ids_gte": 2, "force": "complete"}]),
        explore=phase("fact"),
    )
    pid = _create(http_client, bootstrap_enabled=False)["project"]["id"]
    loop = make_loop(config, client, containers)
    try:
        dispatch_and_wait(loop)  # Reason, even though Bootstrap is disabled
        planned = client.get_project(pid)
        assert len(planned.intents) == 1
        assert planned.intents[0].action_kind is None
        assert planned.coverage_items == []
        assert planned.surface_inventory == []
        dispatch_and_wait(loop)  # Explore
        dispatch_and_wait(loop)  # Reason completion
        done = client.get_project(pid)
        assert done.project.status == "completed"
        assert done.project.mode == "ctf"
        assert done.coverage_items == []
        assert done.surface_inventory == []
        assert done.hypotheses == []
        snapshots = [json.loads(content) for _, path, content in containers.writes if "/graph/" in path or "execute-" in path]
        assert snapshots
        assert all(set(snapshot) == {"project", "facts", "intents", "hints"} for snapshot in snapshots)
    finally:
        loop.close()


def test_incompatible_ctf_project_does_not_break_other_dispatch(http_client):
    from tests.conftest import InProcessClient, LocalContainerManager, make_loop, dispatch_and_wait

    client = InProcessClient(http_client)
    loop = make_loop(_config(), client, LocalContainerManager())
    invalid = _create(http_client, recon_profile={"target_type": "android"})["project"]["id"]
    valid = _create(http_client)["project"]["id"]
    try:
        dispatch_and_wait(loop)
        assert client.get_project(invalid).intents == []
        assert client.get_project(valid).project.status == "completed"
    finally:
        loop.close()


def test_ctf_bootstrap_incomplete_preserves_progress_for_reason(http_client, monkeypatch):
    from skidc.dispatcher.ctf_contracts import validate_ctf_bootstrap_execute_payload
    from skidc.dispatcher.workers.adapters import mock
    from tests.conftest import InProcessClient, LocalContainerManager, make_loop, dispatch_and_wait

    assert validate_ctf_bootstrap_execute_payload({"accepted": True, "data": {"no_result": True}}) == ("incomplete", None)
    # Simulate the real prompt's explicit incomplete outcome; conclude still uses the real mock process.
    script = mock._SCRIPT.replace(
        'phase=prompt["phase"]',
        'phase=prompt["phase"]\n    if phase == "bootstrap":\n        print(json.dumps({"accepted": True, "data": {"no_result": True}}))\n        raise SystemExit(0)',
    )
    monkeypatch.setattr(mock, "_SCRIPT", script)
    client = InProcessClient(http_client)
    loop = make_loop(_config(), client, LocalContainerManager())
    pid = _create(http_client)["project"]["id"]
    try:
        dispatch_and_wait(loop)
        project = client.get_project(pid)
        assert project.project.status == "active"
        assert len(project.facts) == 3
        assert project.intents[0].to == "f001"
        assert "bootstrap_conclude" in project.facts[-1].description
    finally:
        loop.close()


@pytest.mark.parametrize("task", ["reason", "explore"])
def test_ctf_task_rejects_web_payload_in_execute_and_conclude(http_client, monkeypatch, task):
    from skidc.dispatcher.workers.adapters import mock
    from tests.conftest import InProcessClient, LocalContainerManager, make_loop, dispatch_and_wait

    data = ({"intents": [{"from": ["origin"], "description": "web", "action_kind": "verify"}]}
            if task == "reason" else {"description": "must not commit", "severity": "high"})
    monkeypatch.setattr(mock, "_SCRIPT", "import json\nprint(" + repr(json.dumps({"accepted": True, "data": data})) + ")")
    config = _config()
    config.runtime.worker_healthcheck = "disabled"
    client = InProcessClient(http_client)
    loop = make_loop(config, client, LocalContainerManager())
    pid = _create(http_client, bootstrap_enabled=False)["project"]["id"]
    if task == "explore":
        assert client.create_intent(pid, ["origin"], "observe", "test").ok
    try:
        dispatch_and_wait(loop)
        project = client.get_project(pid)
        assert [fact.id for fact in project.facts] == ["origin", "goal"]
        assert len(project.intents) == (1 if task == "explore" else 0)
        assert all(intent.to is None for intent in project.intents)
        assert project.coverage_items == []
        if task == "explore":
            logs = http_client.get(f"/projects/{pid}/logs").json()
            assert any(log["phase"] == "explore_conclude" for log in logs)
    finally:
        loop.close()
