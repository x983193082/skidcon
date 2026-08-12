from __future__ import annotations

from fastapi.testclient import TestClient

import skidc.dispatcher.scheduler.loop as scheduler_loop
from skidc.dispatcher.models import ReasonCheckpoint
from skidc.server.db import get_conn
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
    create_intent,
    create_real_web_project,
    create_required_coverage,
    create_surface,
)


def test_real_web_failure_never_creates_failure_fact_or_dead_letters(http_client):
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
    original_fact_count = len(
        http_client.get(f"/projects/{project_id}").json()["facts"]
    )
    for attempt in range(5):
        claim_intent(http_client, project_id, intent["id"])
        failed = http_client.post(
            f"/projects/{project_id}/intents/{intent['id']}/failure",
            json={
                "worker": "executor",
                "error": f"synthetic failure {attempt}",
                "max_attempts": 3,
                "backoff_seconds": 0,
            },
        )
        assert failed.status_code == 200
        assert failed.json()["status"] == "open"
        assert failed.json()["to"] is None
        assert failed.json()["dead_lettered_at"] is None
    detail = http_client.get(f"/projects/{project_id}").json()
    assert len(detail["facts"]) == original_fact_count


def test_real_web_conclusion_failure_remains_retryable_without_failure_fact(http_client):
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
    task_log = http_client.post(
        f"/projects/{project_id}/logs",
        json={
            "task_type": "explore",
            "intent_id": intent["id"],
            "worker_name": "executor",
            "phase": "explore_execute",
            "stdin": "probe",
            "stdout": "malformed model output",
            "stderr": "",
            "return_code": 0,
            "duration_ms": 10,
        },
    ).json()
    executed = http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/execution-success",
        json={"worker": "executor", "task_log_id": task_log["id"]},
    )
    assert executed.status_code == 200
    original_fact_count = len(
        http_client.get(f"/projects/{project_id}").json()["facts"]
    )
    for _ in range(5):
        failed = http_client.post(
            f"/projects/{project_id}/intents/{intent['id']}/conclusion-failure",
            json={"worker": "executor", "error": "invalid conclusion JSON"},
        )
        assert failed.status_code == 200
        assert failed.json()["status"] == "open"
        assert failed.json()["to"] is None
        assert failed.json()["dead_lettered_at"] is None
    detail = http_client.get(f"/projects/{project_id}").json()
    assert len(detail["facts"]) == original_fact_count


def _run_dispatch_cycle(loop) -> None:
    loop._reap_futures()
    summaries = loop.client.list_projects()
    loop._initialize_reason_checkpoints(summaries)
    loop._refresh_runtime_projects(summaries)
    loop._cancel_inactive_tasks(summaries)
    loop._queue_container_cleanups(summaries)
    loop._dispatch_available(summaries)
    for future in list(loop.futures):
        future.result(timeout=10)
    loop._reap_futures()


def test_intents_expose_retry_and_dead_letter_state(http_client: TestClient) -> None:
    project_id = http_client.post(
        "/projects",
        json={"title": "t", "origin": "o", "goal": "g"},
    ).json()["project"]["id"]

    response = http_client.post(
        f"/projects/{project_id}/intents",
        json={"from": ["origin"], "description": "probe", "creator": "reasoner"},
    )

    assert response.status_code == 201
    intent = response.json()
    assert intent["status"] == "open"
    assert intent["attempt_count"] == 0
    assert intent["last_error"] is None
    assert intent["next_retry_at"] is None
    assert intent["dead_lettered_at"] is None


def test_web_project_read_expires_stale_intent_and_reason_leases(
    http_client: TestClient,
) -> None:
    project_id = create_project(
        http_client, bootstrap_enabled=False, required_recon_categories=[],
    )
    intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "legacy executable work",
            "creator": "reasoner",
        },
    ).json()
    assert http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/heartbeat",
        json={"worker": "stale-explorer"},
    ).status_code == 200
    assert http_client.post(
        f"/projects/{project_id}/reason/claim",
        json={"worker": "stale-reasoner", "trigger": "test"},
    ).status_code == 200
    with get_conn() as conn:
        conn.execute(
            "UPDATE intents SET last_heartbeat_at = ? WHERE project_id = ? AND id = ?",
            ("2000-01-01 00:00:00", project_id, intent["id"]),
        )
        conn.execute(
            "UPDATE projects SET reason_last_heartbeat_at = ? WHERE id = ?",
            ("2000-01-01 00:00:00", project_id),
        )

    detail = http_client.get(f"/projects/{project_id}").json()
    refreshed_intent = next(item for item in detail["intents"] if item["id"] == intent["id"])
    assert refreshed_intent["worker"] is None
    assert refreshed_intent["last_heartbeat_at"] is None
    assert detail["project"]["reason"] is None


def test_intent_failure_records_retry_then_result_fact(http_client: TestClient) -> None:
    project_id = http_client.post(
        "/projects",
        json={"title": "t", "origin": "o", "goal": "g"},
    ).json()["project"]["id"]
    intent_id = http_client.post(
        f"/projects/{project_id}/intents",
        json={"from": ["origin"], "description": "probe", "creator": "reasoner"},
    ).json()["id"]

    first = http_client.post(
        f"/projects/{project_id}/intents/{intent_id}/failure",
        json={"worker": "w1", "error": "invalid_json", "max_attempts": 3, "backoff_seconds": 30},
    )
    second = http_client.post(
        f"/projects/{project_id}/intents/{intent_id}/failure",
        json={"worker": "w1", "error": "invalid_json", "max_attempts": 3, "backoff_seconds": 0},
    )
    third = http_client.post(
        f"/projects/{project_id}/intents/{intent_id}/failure",
        json={"worker": "w1", "error": "invalid_json", "max_attempts": 3, "backoff_seconds": 0},
    )

    assert first.status_code == 200
    assert first.json()["attempt_count"] == 1
    assert first.json()["status"] == "open"
    assert first.json()["next_retry_at"]
    assert first.json()["last_worker"] == "w1"
    assert second.status_code == 200
    assert second.json()["attempt_count"] == 2
    assert second.json()["status"] == "open"
    assert third.status_code == 200
    assert third.json()["attempt_count"] == 3
    assert third.json()["status"] == "concluded"
    assert third.json()["execution_status"] == "failed"
    assert third.json()["to"] is not None
    assert http_client.get(f"/projects/{project_id}").json()["facts"][-1]["status"] is None
    assert third.json()["dead_lettered_at"]
    assert third.json()["next_retry_at"] is None


def test_conclusion_failure_also_produces_result_fact(http_client: TestClient) -> None:
    project_id = http_client.post(
        "/projects", json={"title": "t", "origin": "o", "goal": "g"},
    ).json()["project"]["id"]
    intent = http_client.post(
        f"/projects/{project_id}/intents",
        json={"from": ["origin"], "description": "probe", "creator": "reasoner"},
    ).json()
    http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/heartbeat",
        json={"worker": "w1"},
    )
    task_log = http_client.post(
        f"/projects/{project_id}/logs",
        json={
            "task_type": "explore",
            "intent_id": intent["id"],
            "worker_name": "w1",
            "phase": "explore_execute",
            "stdin": "probe",
            "stdout": "unparseable result",
            "stderr": "",
            "return_code": 0,
            "duration_ms": 10,
        },
    ).json()
    executed = http_client.post(
        f"/projects/{project_id}/intents/{intent['id']}/execution-success",
        json={"worker": "w1", "task_log_id": task_log["id"]},
    )
    assert executed.status_code == 200

    result = None
    for _ in range(3):
        result = http_client.post(
            f"/projects/{project_id}/intents/{intent['id']}/conclusion-failure",
            json={"worker": "w1", "error": "invalid conclusion JSON"},
        )
        assert result.status_code == 200
    assert result is not None
    terminal = result.json()
    assert terminal["status"] == "concluded"
    assert terminal["execution_status"] == "succeeded"
    assert terminal["to"] is not None

    detail = http_client.get(f"/projects/{project_id}").json()
    fact = next(item for item in detail["facts"] if item["id"] == terminal["to"])
    assert fact["kind"] == "execution_result"
    assert fact["status"] is None
    assert fact["data"]["failure_stage"] == "conclusion_failed"
    assert fact["task_log_refs"] == [task_log["id"]]


def test_intent_failure_updates_bound_coverage_lifecycle(http_client: TestClient) -> None:
    project_id = http_client.post(
        "/projects",
        json={"title": "t", "origin": "o", "goal": "g", "mode": "real_website"},
    ).json()["project"]["id"]
    coverage_id = http_client.post(
        f"/projects/{project_id}/coverage",
        json={
            "item_type": "vuln_class",
            "description": "Test login authentication behavior.",
            "test_family": "identity_auth",
            "surface_group": "auth:/login",
            "priority": 8,
        },
    ).json()["id"]
    intent_id = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "Test login.",
            "creator": "reasoner",
            "coverage_refs": [coverage_id],
        },
    ).json()["id"]

    http_client.post(
        f"/projects/{project_id}/intents/{intent_id}/heartbeat",
        json={"worker": "w1"},
    )
    retry = http_client.post(
        f"/projects/{project_id}/intents/{intent_id}/failure",
        json={"worker": "w1", "error": "timeout", "max_attempts": 2, "backoff_seconds": 0},
    )
    assert retry.status_code == 200
    queued = http_client.get(f"/projects/{project_id}/coverage").json()[0]
    assert queued["execution_status"] == "queued"
    assert queued["outcome"] is None

    dead = http_client.post(
        f"/projects/{project_id}/intents/{intent_id}/failure",
        json={"worker": "w1", "error": "timeout", "max_attempts": 2, "backoff_seconds": 0},
    )
    assert dead.status_code == 200
    inconclusive = http_client.get(f"/projects/{project_id}/coverage").json()[0]
    assert inconclusive["execution_status"] == "queued"
    assert inconclusive["outcome"] is None
    assert inconclusive["status"] == "untested"

    replacement = http_client.post(
        f"/projects/{project_id}/intents",
        json={
            "from": ["origin"],
            "description": "Retry login with an alternate method.",
            "creator": "reasoner",
            "coverage_refs": [coverage_id],
        },
    )
    assert replacement.status_code == 201
    requeued = http_client.get(f"/projects/{project_id}/coverage").json()[0]
    assert requeued["execution_status"] == "queued"
    assert requeued["status"] == "untested"


def test_scheduler_skips_intents_until_next_retry_at(http_client: TestClient) -> None:
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
    project_id = create_project(http_client, bootstrap_enabled=False)
    try:
        intent = client.create_intent(project_id, ["origin"], "delayed probe", "test").data
        assert isinstance(intent, dict)
        assert client.record_intent_failure(
            project_id,
            intent["id"],
            "test-worker",
            "transient failure",
            max_attempts=3,
            backoff_seconds=60,
        ).ok
        loop.reason_checkpoints[project_id] = ReasonCheckpoint(fact_count=2, hint_count=0, open_intent_count=1)

        _run_dispatch_cycle(loop)

        assert not loop.futures
        delayed = http_client.get(f"/projects/{project_id}").json()["intents"][0]
        assert delayed["status"] == "open"
        assert delayed["attempt_count"] == 1
        assert delayed["next_retry_at"]
        assert delayed["to"] is None
    finally:
        loop.close()


def test_failed_result_fact_does_not_block_other_explore_paths(http_client: TestClient) -> None:
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
    try:
        dead = client.create_intent(project_id, ["origin"], "failing direction", "test").data
        live = client.create_intent(project_id, ["origin"], "alternative direction", "test").data
        assert isinstance(dead, dict)
        assert isinstance(live, dict)
        assert client.record_intent_failure(
            project_id,
            dead["id"],
            "test-worker",
            "repeated failure",
            max_attempts=1,
            backoff_seconds=0,
        ).ok
        loop.reason_checkpoints[project_id] = ReasonCheckpoint(fact_count=2, hint_count=0, open_intent_count=2)

        _run_dispatch_cycle(loop)
        _run_dispatch_cycle(loop)
        _run_dispatch_cycle(loop)  # Reason may complete only after both Fact edges are committed.
        _run_dispatch_cycle(loop)  # The final Fact change receives its Reason pass.

        project = http_client.get(f"/projects/{project_id}").json()
        intents = {intent["id"]: intent for intent in project["intents"]}
        assert intents[dead["id"]]["status"] == "concluded"
        assert intents[dead["id"]]["to"] is not None
        assert next(fact for fact in project["facts"] if fact["id"] == intents[dead["id"]]["to"])["status"] is None
        assert intents[live["id"]]["status"] == "concluded"
        assert intents[live["id"]]["to"] is not None
        assert project["project"]["status"] == "completed"
    finally:
        loop.close()


def test_bootstrap_failure_is_terminal_and_project_can_complete(http_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(scheduler_loop, "RETRY_BACKOFF_SECONDS", (0, 0, 0))
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("command_fail"),
            reason=phase("complete"),
            explore=phase("fact"),
        ),
        client,
        containers,
    )
    project_id = create_project(http_client, bootstrap_enabled=True)
    try:
        for _ in range(4):
            _run_dispatch_cycle(loop)

        project = http_client.get(f"/projects/{project_id}").json()
    finally:
        loop.close()

    bootstrap_intents = [
        intent for intent in project["intents"]
        if intent["description"] == "bootstrap"
    ]
    assert len(bootstrap_intents) == 1
    assert bootstrap_intents[0]["status"] == "concluded"
    assert bootstrap_intents[0]["to"] is not None
    assert project["project"]["status"] == "completed"

def test_real_web_explore_failure_remains_retryable_after_repeated_attempts(
    http_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(scheduler_loop, "RETRY_BACKOFF_SECONDS", (0, 0, 0))
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            reason=phase("complete"),
            explore=phase("command_fail"),
        ),
        client,
        containers,
    )
    project_id = create_project(
        http_client, bootstrap_enabled=False, required_recon_categories=[]
    )
    advanced = http_client.post(f"/projects/{project_id}/phase/advance", json={})
    assert advanced.status_code == 200 and advanced.json()["advanced"]
    try:
        assert client.create_intent(project_id, ["origin"], "deterministic failing probe", "test").ok
        loop.reason_checkpoints[project_id] = ReasonCheckpoint(fact_count=2, hint_count=0, open_intent_count=1)

        for _ in range(4):
            _run_dispatch_cycle(loop)

        project = http_client.get(f"/projects/{project_id}").json()
    finally:
        loop.close()

    intent = project["intents"][0]
    assert intent["status"] == "open"
    assert intent["execution_status"] in {"failed", "running"}
    assert intent["to"] is None
    assert intent["attempt_count"] == 4
    assert intent["last_error"]
    assert intent["dead_lettered_at"] is None
    assert project["project"]["status"] == "active"


def test_reason_failures_are_visible_on_project(http_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(scheduler_loop, "RETRY_BACKOFF_SECONDS", (0, 0, 0))
    client = InProcessClient(http_client)
    containers = LocalContainerManager()
    loop = make_loop(
        mock_config(
            bootstrap=phase("complete"),
            reason=phase("invalid_json"),
            explore=phase("fact"),
        ),
        client,
        containers,
    )
    project_id = create_project(http_client, bootstrap_enabled=False, required_recon_categories=[])
    advanced = http_client.post(f"/projects/{project_id}/phase/advance", json={})
    assert advanced.status_code == 200 and advanced.json()["advanced"]
    try:
        for _ in range(3):
            dispatch_and_wait(loop)

        project = http_client.get(f"/projects/{project_id}").json()["project"]
    finally:
        loop.close()

    assert project["status"] == "stopped"
    assert project["run_state"] == "needs_attention"
    assert project["completion_outcome"] == "needs_attention"
    assert project["stop_reason_code"] == "reason_retry_exhausted"
    assert project["reason_attempt_count"] == 3
    assert project["reason_dead_lettered_at"] is not None
    assert project["reason_next_retry_at"] is None
    report = http_client.get(f"/projects/{project_id}/export?format=report").text
    assert "reason_retry_exhausted" in report


def test_reason_complete_finishes_terminal_explore_project(http_client: TestClient) -> None:
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
    try:
        dispatch_and_wait(loop)
        project = client.get_project(project_id)
    finally:
        loop.close()

    assert project.project.status == "completed"
    assert all(intent.status == "concluded" for intent in project.intents)
