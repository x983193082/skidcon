from __future__ import annotations

from fastapi.testclient import TestClient

from skidc.dispatcher.models import ReasonCheckpoint
from tests.conftest import (
    InProcessClient,
    LocalContainerManager,
    create_project,
    dispatch_and_wait,
    make_loop,
    mock_config,
    phase,
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
        assert loop.reason_checkpoints[project_id] == ReasonCheckpoint(3, 0, 0)
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
