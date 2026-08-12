"""Unit tests for dispatcher helpers that the end-to-end mock suite does not
exercise in isolation: worker ordering, container archive path-safety, task
cancellation semantics, and the reason re-trigger checkpoint logic.

These mirror the coverage points of Cairn's test_scheduler_logic / test_runtime_logic
but are written fresh against Skidc's own implementation."""

from __future__ import annotations

from concurrent.futures import Future
import io
import tarfile
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from skidc.dispatcher.config import AndroidBridgeConfig, DispatchConfig, WorkerConfig
from skidc.dispatcher.models import ReasonCheckpoint, RunningTask
from skidc.dispatcher.runtime.cancellation import TaskCancellation
from skidc.dispatcher.runtime.containers import ContainerManager
from skidc.dispatcher.runtime.startup_healthcheck import StartupHealthcheckResult, missing_healthy_task_types
from skidc.dispatcher.scheduler.loop import DispatcherLoop
from skidc.dispatcher.scheduler.worker_select import choose_worker
from skidc.dispatcher.tasks.common import format_worker_input
from skidc.dispatcher.tasks.common import prepare_android_bridge
from skidc.dispatcher.runtime.process import ProcessResult
from skidc.dispatcher.protocol.client import ApiResult
from skidc.server.models import Fact, Hint, Intent, ProjectDetail, ProjectMeta, ProjectSummary
from tests.conftest import InProcessClient, LocalContainerManager, make_loop, mock_config, phase


# --------------------------------------------------------------------------- #
# worker selection ordering                                                    #
# --------------------------------------------------------------------------- #


def _worker(name: str, priority: int) -> WorkerConfig:
    return WorkerConfig.model_validate(
        {
            "name": name,
            "type": "mock",
            "task_types": ["explore"],
            "max_running": 4,
            "priority": priority,
            "env": {},
        }
    )


def test_choose_worker_prefers_lower_priority_number_first() -> None:
    a = _worker("a", priority=1)
    b = _worker("b", priority=0)
    ordered = choose_worker([a, b], running_counts={})
    assert ordered[0].name == "b"  # priority 0 beats priority 1


def test_choose_worker_breaks_priority_tie_by_fewest_running() -> None:
    a = _worker("a", priority=0)
    b = _worker("b", priority=0)
    ordered = choose_worker([a, b], running_counts={"a": 3, "b": 1})
    assert ordered[0].name == "b"  # same priority -> fewer running wins


def test_choose_worker_empty_candidates_returns_empty() -> None:
    assert choose_worker([], running_counts={}) == []


# --------------------------------------------------------------------------- #
# container archive path safety (_text_file_archive)                           #
# --------------------------------------------------------------------------- #


def test_text_file_archive_builds_tar_for_nested_path() -> None:
    archive_path, blob = ContainerManager._text_file_archive(
        "/tmp/skidc-prompts/abc/graph.yaml", "hello: world"
    )
    # put_archive extracts the tar *into* the first path segment
    assert archive_path == "/tmp"
    assert isinstance(blob, bytes) and blob  # non-empty tar stream


@pytest.mark.parametrize(
    "bad_path",
    [
        "relative/path.txt",   # not absolute
        "/",                   # no file component
        "/foo/..",             # traversal component (trailing)
        "/foo/../bar",         # traversal component (mid-path)
        "",                    # empty
    ],
)
def test_text_file_archive_rejects_unsafe_paths(bad_path: str) -> None:
    with pytest.raises(ValueError):
        ContainerManager._text_file_archive(bad_path, "x")


def test_text_file_archive_normalizes_dot_segment() -> None:
    # a single "." segment is normalized away by PurePosixPath and is safe
    archive_path, blob = ContainerManager._text_file_archive("/foo/./bar.txt", "x")
    assert archive_path == "/foo"
    assert blob


def test_text_file_archive_applies_explicit_secret_mode() -> None:
    _, blob = ContainerManager._text_file_archive(
        "/run/skidc/android-mcp-token",
        "secret-token\n",
        mode=0o600,
        uid=1000,
        gid=1000,
    )

    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as archive:
        token = archive.getmember("skidc/android-mcp-token")

    assert token.mode == 0o600
    assert token.uid == 1000
    assert token.gid == 1000


@pytest.mark.parametrize("mode", [-1, 0, 0o1000])
def test_text_file_archive_rejects_invalid_mode(mode: int) -> None:
    with pytest.raises(ValueError, match="mode"):
        ContainerManager._text_file_archive("/tmp/token", "x", mode=mode)


class _PreparationProcess:
    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.started = False

    def start(self) -> None:
        self.started = True

    def communicate(self, timeout: float | None) -> ProcessResult:
        assert self.started
        assert timeout == 17
        return self.result


class _PreparationContainerManager:
    def __init__(self, result: ProcessResult) -> None:
        self.result = result
        self.writes: list[tuple[str, str, str, int, int, int]] = []
        self.execs: list[tuple[str, dict[str, str], list[str], int | None]] = []

    def write_text_file(
        self,
        container_name: str,
        path: str,
        content: str,
        *,
        mode: int = 0o644,
        uid: int = 0,
        gid: int = 0,
    ) -> None:
        self.writes.append((container_name, path, content, mode, uid, gid))

    def build_exec_process(
        self,
        container_name: str,
        env: dict[str, str],
        command: list[str],
        timeout_seconds: int | None = None,
        kill_after_seconds: int = 5,
    ) -> _PreparationProcess:
        assert kill_after_seconds == 5
        self.execs.append((container_name, env, command, timeout_seconds))
        return _PreparationProcess(self.result)


def test_prepare_android_bridge_provisions_secret_and_checks_readiness(tmp_path) -> None:
    token_file = tmp_path / "android_mcp_token"
    token_file.write_text("secret-token\n", encoding="utf-8")
    config = SimpleNamespace(
        android_bridge=SimpleNamespace(
            token_file=str(token_file),
            worker_token_file="/run/skidc/android-mcp-token",
            readiness_timeout=2,
        )
    )
    worker = _worker("android", priority=0).model_copy(
        update={
            "env": {
                "ANDROID_MCP_URL": "http://127.0.0.1:8765",
                "ANDROID_MCP_TOKEN_FILE": "/run/skidc/android-mcp-token",
            }
        }
    )
    manager = _PreparationContainerManager(
        ProcessResult(returncode=0, stdout='{"ready":true}', stderr="")
    )

    result = prepare_android_bridge(config, manager, "worker-1", worker)

    assert result is not None and result.returncode == 0
    assert manager.writes == [
        ("worker-1", "/run/skidc/android-mcp-token", "secret-token\n", 0o600, 1000, 1000)
    ]
    assert manager.execs == [
        (
            "worker-1",
            worker.env,
            ["android-mcp", "GET", "/health/ready"],
            2,
        )
    ]
    assert "secret-token" not in repr(manager.execs)


def test_prepare_android_bridge_skips_non_android_worker_without_reading_secret() -> None:
    config = SimpleNamespace(
        android_bridge=SimpleNamespace(
            token_file="/missing/token",
            worker_token_file="/run/skidc/android-mcp-token",
            readiness_timeout=2,
        )
    )
    worker = _worker("web", priority=0)
    manager = _PreparationContainerManager(
        ProcessResult(returncode=0, stdout="", stderr="")
    )

    result = prepare_android_bridge(config, manager, "worker-1", worker)

    assert result is None
    assert manager.writes == []
    assert manager.execs == []


def test_worker_input_log_summarizes_operation_without_prompt_body() -> None:
    prompt = (
        "# Task\n"
        "SECRET PROMPT BODY SHOULD NOT BE STORED\n\n"
        "The graph YAML snapshot is stored in this file inside the current container:\n\n"
        "/tmp/skidc-prompts/explore_execute-abc123/graph.yaml\n\n"
        "Before using the graph, read it."
    )
    summary = format_worker_input(
        prompt,
        ["claude", "-p", prompt],
        task_type="explore",
        phase="explore_execute",
        worker_name="w1",
        operation="explore assigned intent",
        project_id="proj_001",
        intent_id="i001",
        intent_description="Probe upload bypass",
        target="example.test",
        port=80,
        surface_type="web",
        action_kind="upload_probe",
        priority=10,
        suggested_tools=["curl"],
        timeout_seconds=60,
    )

    assert "intent_description: Probe upload bypass" in summary
    assert "graph_snapshot: /tmp/skidc-prompts/explore_execute-abc123/graph.yaml" in summary
    assert "<omitted long argument chars=" in summary
    assert "SECRET PROMPT BODY SHOULD NOT BE STORED" not in summary
    assert "prompt:" not in summary.lower()


# --------------------------------------------------------------------------- #
# task cancellation semantics                                                  #
# --------------------------------------------------------------------------- #


def test_cancellation_first_reason_wins_and_returns_true_once() -> None:
    c = TaskCancellation()
    assert c.cancel("project-stopped") is True
    # a second cancel does not overwrite the reason and returns False
    assert c.cancel("project-deleted") is False
    assert c.reason == "project-stopped"
    assert c.is_cancelled is True


def test_cancellation_starts_uncancelled() -> None:
    c = TaskCancellation()
    assert c.is_cancelled is False
    assert c.reason is None


# --------------------------------------------------------------------------- #
# reason re-trigger checkpoint logic (_reason_trigger)                         #
# --------------------------------------------------------------------------- #


def _project(*, facts: int, hints: int, open_intents: int) -> ProjectDetail:
    meta = ProjectMeta.model_validate(
        {
            "id": "proj_001",
            "title": "t",
            "status": "active",
            "bootstrap_enabled": True,
            "created_at": "2025-01-01T00:00:00Z",
        }
    )
    fact_list = [Fact(id=f"f{i}", description="d") for i in range(facts)]
    hint_list = [
        Hint(id=f"h{i}", content="c", creator="user", created_at="2025-01-01T00:00:00Z")
        for i in range(hints)
    ]
    intent_list = [
        Intent.model_validate(
            {
                "id": f"i{i}",
                "from": ["f0"],
                "to": None,  # open intent
                "description": "d",
                "creator": "w",
                "created_at": "2025-01-01T00:00:00Z",
            }
        )
        for i in range(open_intents)
    ]
    return ProjectDetail(project=meta, facts=fact_list, intents=intent_list, hints=hint_list)


def _bare_loop() -> DispatcherLoop:
    loop = DispatcherLoop.__new__(DispatcherLoop)
    loop.reason_checkpoints = {}
    return loop


def test_dispatcher_selects_prompt_config_from_project_target_type() -> None:
    config = mock_config(
        bootstrap=phase("complete"),
        reason=phase("intent"),
        explore=phase("fact"),
    )
    config.runtime.target_prompt_groups["android"] = "android"
    loop = _bare_loop()
    loop.config = config
    project = _project(facts=0, hints=0, open_intents=0)

    project.project.recon_profile.target_type = "android"
    assert loop._config_for_project(project).runtime.prompt_group == "android"

    project.project.recon_profile.target_type = "domain"
    assert loop._config_for_project(project).runtime.prompt_group == "mock"
    assert loop.config.runtime.prompt_group == "mock"


def test_android_explore_submission_receives_target_local_worker(tmp_path) -> None:
    config = mock_config(
        bootstrap=phase("complete"), reason=phase("intent"), explore=phase("fact"),
    )
    config.runtime.target_prompt_groups["android"] = "android"
    config.android_bridge = AndroidBridgeConfig(
        url="http://127.0.0.1:8765",
        token_file=str(tmp_path / "android_mcp_token"),
    )
    loop = _bare_loop()
    loop.config = config
    loop.futures = {}
    loop.worker_unhealthy_until = {}
    loop.worker_rejected_until = {}
    loop.startup_unhealthy_workers = set()
    loop.runtime_project_ids = set()
    loop._log_state = {}
    loop.container_manager = object()

    class _Client:
        def heartbeat(self, _project_id: str, _intent_id: str, _worker: str) -> ApiResult:
            return ApiResult(200, {})

    class _Executor:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def submit(self, *args: object) -> Future[str]:
            self.calls.append(args)
            return Future()

    loop.client = _Client()
    loop.executor = _Executor()
    project = _project(facts=1, hints=0, open_intents=1)
    project.project.recon_profile.target_type = "android"
    intent = project.intents[0]

    assert loop._dispatch_explore(project, "graph", intent) is True

    submitted_worker = loop.executor.calls[0][7]
    assert isinstance(submitted_worker, WorkerConfig)
    assert submitted_worker.env["ANDROID_MCP_URL"] == "http://127.0.0.1:8765"
    assert submitted_worker.env["ANDROID_MCP_TOKEN_FILE"] == "/run/skidc/android-mcp-token"
    assert "ANDROID_MCP_URL" not in config.workers[0].env


def test_reason_trigger_initial_when_no_checkpoint() -> None:
    loop = _bare_loop()
    project = _project(facts=2, hints=0, open_intents=1)
    assert loop._reason_trigger(project) == "initial"


def test_reason_trigger_none_when_graph_unchanged() -> None:
    loop = _bare_loop()
    loop.reason_checkpoints["proj_001"] = ReasonCheckpoint(
        fact_count=2, hint_count=0, open_intent_count=1
    )
    project = _project(facts=2, hints=0, open_intents=1)
    assert loop._reason_trigger(project) is None


def test_reason_trigger_detects_new_fact() -> None:
    loop = _bare_loop()
    loop.reason_checkpoints["proj_001"] = ReasonCheckpoint(
        fact_count=2, hint_count=0, open_intent_count=1
    )
    project = _project(facts=3, hints=0, open_intents=1)
    trigger = loop._reason_trigger(project)
    assert trigger is not None and "facts:2->3" in trigger


def test_reason_trigger_new_fact_bypasses_backoff_from_older_graph() -> None:
    loop = _bare_loop()
    loop.reason_checkpoints["proj_001"] = ReasonCheckpoint(
        fact_count=2, hint_count=0, open_intent_count=1
    )
    project = _project(facts=3, hints=0, open_intents=1)
    project.project = project.project.model_copy(
        update={"reason_next_retry_at": "2999-01-01T00:00:00Z"}
    )

    assert loop._reason_trigger(project) == "facts:2->3"


def test_real_website_reason_trigger_detects_new_fact_with_open_intent() -> None:
    """A completed Explore must return to Reason even when other Intents remain open."""
    loop = _bare_loop()
    loop.futures = {}
    loop.reason_checkpoints["proj_001"] = ReasonCheckpoint(
        fact_count=2, hint_count=0, open_intent_count=1
    )
    project = _project(facts=3, hints=0, open_intents=1)
    project.project = project.project.model_copy(
        update={"mode": "real_website", "phase": "explore", "planning_version": 3}
    )

    assert loop._reason_trigger(project) == "facts:2->3"


def test_real_website_new_fact_dispatches_reason_before_v3_coverage(
    monkeypatch,
) -> None:
    """V3 coverage generation must not pre-empt analysis of a newly written Fact."""
    loop = _bare_loop()
    loop.config = mock_config(
        bootstrap=phase("complete"),
        reason=phase("intent"),
        explore=phase("fact"),
    )
    loop.container_manager = LocalContainerManager()
    loop.futures = {}
    loop._cleanup_pending = set()

    project = _project(facts=3, hints=0, open_intents=1)
    project.project = project.project.model_copy(
        update={"mode": "real_website", "phase": "explore", "planning_version": 3}
    )
    loop.reason_checkpoints["proj_001"] = ReasonCheckpoint(
        fact_count=2, hint_count=0, open_intent_count=1
    )

    class _Client:
        def get_project(self, _project_id: str) -> ProjectDetail:
            return project

        def export_project(self, _project_id: str) -> str:
            return "graph"

    loop.client = _Client()
    calls: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        "skidc.dispatcher.scheduler.loop.ensure_coverage_work",
        lambda *_args: calls.append(("coverage", None)) or 1,
        raising=False,
    )
    monkeypatch.setattr(
        loop,
        "_dispatch_reason",
        lambda _project, _graph, trigger: calls.append(("reason", trigger)) or True,
    )

    summary = ProjectSummary.model_validate(
        {
            "id": "proj_001",
            "title": "t",
            "status": "active",
            "bootstrap_enabled": True,
            "phase": "explore",
            "mode": "real_website",
            "created_at": "2025-01-01T00:00:00Z",
            "fact_count": 3,
            "intent_count": 1,
            "working_intent_count": 0,
            "unclaimed_intent_count": 1,
            "hint_count": 0,
        }
    )

    assert loop._try_dispatch_project(summary) is True
    assert calls == [("reason", "facts:2->3")]


def test_real_website_stable_graph_does_not_invoke_v3_coverage(monkeypatch) -> None:
    """Surface indexing is read-only and must never manufacture scheduler work."""
    loop = _bare_loop()
    loop.config = mock_config(
        bootstrap=phase("complete"),
        reason=phase("intent"),
        explore=phase("fact"),
    )
    loop.container_manager = LocalContainerManager()
    loop.futures = {}
    loop._cleanup_pending = set()

    project = _project(facts=2, hints=0, open_intents=0)
    project.project = project.project.model_copy(
        update={"mode": "real_website", "phase": "explore", "planning_version": 3}
    )
    loop.reason_checkpoints["proj_001"] = ReasonCheckpoint(
        fact_count=2, hint_count=0, open_intent_count=0
    )

    class _Client:
        def get_project(self, _project_id: str) -> ProjectDetail:
            return project

    loop.client = _Client()
    calls: list[str] = []
    monkeypatch.setattr(
        "skidc.dispatcher.scheduler.loop.ensure_coverage_work",
        lambda *_args: calls.append("coverage") or 1,
        raising=False,
    )

    summary = ProjectSummary.model_validate(
        {
            "id": "proj_001",
            "title": "t",
            "status": "active",
            "bootstrap_enabled": True,
            "phase": "explore",
            "mode": "real_website",
            "created_at": "2025-01-01T00:00:00Z",
            "fact_count": 2,
            "intent_count": 0,
            "working_intent_count": 0,
            "unclaimed_intent_count": 0,
            "hint_count": 0,
        }
    )

    assert loop._try_dispatch_project(summary) is False
    assert calls == []


def test_reason_trigger_detects_open_intents_drained_to_zero() -> None:
    loop = _bare_loop()
    loop.reason_checkpoints["proj_001"] = ReasonCheckpoint(
        fact_count=2, hint_count=0, open_intent_count=2
    )
    project = _project(facts=2, hints=0, open_intents=0)
    trigger = loop._reason_trigger(project)
    assert trigger is not None and "open_intents:2->0" in trigger


def test_reason_trigger_does_not_run_when_graph_is_unchanged() -> None:
    loop = _bare_loop()
    loop.reason_checkpoints["proj_001"] = ReasonCheckpoint(
        fact_count=2, hint_count=0, open_intent_count=0
    )
    project = _project(facts=2, hints=0, open_intents=0)
    project.project = project.project.model_copy(
        update={
            "completion_blocked_at": "2025-01-01T00:00:00Z",
            "run_state": "completion_blocked",
        }
    )

    assert loop._reason_trigger(project) is None


def test_completion_blocked_reason_is_recorded_as_failure_not_success() -> None:
    loop = _bare_loop()
    loop.worker_unhealthy_until = {}
    loop.worker_rejected_until = {}
    loop._log_state = {}
    failed: list[tuple[str, str]] = []
    succeeded: list[str] = []
    loop._record_task_failure = lambda task, outcome: failed.append((task.project_id, outcome))
    loop._record_reason_success = lambda task: succeeded.append(task.project_id)
    project = _project(facts=2, hints=0, open_intents=0)

    class _Client:
        def get_project(self, _project_id: str) -> ProjectDetail:
            return project

    loop.client = _Client()

    future: Future[str] = Future()
    future.set_result("completion_blocked")
    loop.futures = {
        future: RunningTask("proj_001", "reason", "reasoner", TaskCancellation())
    }

    loop._reap_futures()

    assert failed == [("proj_001", "completion_blocked")]
    assert succeeded == []
    assert loop.reason_checkpoints["proj_001"] == ReasonCheckpoint(2, 0, 0)


def test_android_dependency_failure_is_project_retryable_not_worker_unhealthy() -> None:
    loop = _bare_loop()
    loop.worker_unhealthy_until = {}
    loop.worker_rejected_until = {}
    loop._log_state = {}
    failed: list[tuple[str, str]] = []
    loop._record_task_failure = lambda task, outcome: failed.append((task.project_id, outcome))

    future: Future[str] = Future()
    future.set_result("dependency_unavailable")
    loop.futures = {
        future: RunningTask(
            "android-project", "explore", "shared-worker", TaskCancellation(),
            intent_id="i001",
        )
    }

    loop._reap_futures()

    assert failed == [("android-project", "dependency_unavailable")]
    assert "shared-worker" not in loop.worker_unhealthy_until

# --------------------------------------------------------------------------- #
# phase 8 scheduler/runtime reliability                                        #
# --------------------------------------------------------------------------- #


def test_potential_target_extraction_is_fact_idempotent_across_dispatcher_restart(
    http_client: TestClient,
) -> None:
    client = InProcessClient(http_client)
    project_id = http_client.post(
        "/projects",
        json={"title": "t", "origin": "https://example.test", "goal": "g", "bootstrap_enabled": False},
    ).json()["project"]["id"]
    assert http_client.post(
        f"/projects/{project_id}/facts",
        json={
            "description": "nmap found 443/tcp https and https://admin.example.test/admin",
            "recon_category": "port_scan",
            "recon_executed": True,
            "recon_found_results": True,
        },
    ).status_code == 201
    project = client.get_project(project_id)

    first_loop = make_loop(mock_config(bootstrap=phase("complete"), reason=phase("complete"), explore=phase("fact")), client, LocalContainerManager())
    second_loop = make_loop(mock_config(bootstrap=phase("complete"), reason=phase("complete"), explore=phase("fact")), client, LocalContainerManager())
    try:
        first_loop._try_extract_potential_targets(project)
        second_loop._try_extract_potential_targets(client.get_project(project_id))
        facts = client.get_project(project_id).facts
    finally:
        first_loop.close()
        second_loop.close()

    potential_targets = [fact.description for fact in facts if fact.goal_type == "potential_target"]
    assert potential_targets
    assert len(potential_targets) == len(set(potential_targets))


def test_running_project_count_uses_live_tasks_not_historical_runtime_set() -> None:
    loop = _bare_loop()
    loop.futures = {}
    loop.runtime_project_ids = {"proj_001", "proj_002"}
    summaries = [
        ProjectSummary.model_validate({
            "id": "proj_001", "title": "one", "status": "active", "bootstrap_enabled": False,
            "phase": "recon", "mode": "real_website", "created_at": "2025-01-01T00:00:00Z",
            "fact_count": 2, "intent_count": 0, "working_intent_count": 0,
            "unclaimed_intent_count": 0, "hint_count": 0,
        }),
        ProjectSummary.model_validate({
            "id": "proj_002", "title": "two", "status": "active", "bootstrap_enabled": False,
            "phase": "recon", "mode": "real_website", "created_at": "2025-01-01T00:00:00Z",
            "fact_count": 2, "intent_count": 0, "working_intent_count": 0,
            "unclaimed_intent_count": 0, "hint_count": 0,
        }),
    ]

    assert loop._running_project_count(summaries) == 0

    future: Future[str] = Future()
    loop.futures[future] = RunningTask("proj_002", "reason", "w", TaskCancellation())

    assert loop._running_project_count(summaries) == 1


def test_recon_intent_selection_prefers_missing_category_then_fifo() -> None:
    loop = _bare_loop()
    project = _project(facts=2, hints=0, open_intents=0)
    project.project.phase = "recon"
    project.project.mode = "real_website"
    project.project.recon_profile.required_categories = ["port_scan", "directory"]
    project.facts.append(Fact(id="f_done", description="done", recon_category="port_scan", recon_executed=True))
    old_directory = Intent.model_validate({
        "id": "i_old", "from": ["origin"], "to": None, "description": "Run directory inventory",
        "creator": "reasoner", "created_at": "2025-01-01T00:00:00Z", "action_kind": "directory_scan",
    })
    new_unrelated = Intent.model_validate({
        "id": "i_new", "from": ["origin"], "to": None, "description": "Check something else",
        "creator": "reasoner", "created_at": "2025-01-02T00:00:00Z",
    })

    assert loop._select_next_intent(project, [new_unrelated, old_directory]).id == "i_old"


def test_startup_healthcheck_requires_healthy_worker_for_each_enabled_task_type() -> None:
    config = DispatchConfig.model_validate({
        "server": "in-process",
        "runtime": {
            "interval": 1, "max_workers": 2, "max_running_projects": 2,
            "max_project_workers": 1, "healthcheck_timeout": 2, "prompt_group": "mock",
        },
        "tasks": {
            "bootstrap": {"timeout": 2, "conclude_timeout": 2},
            "reason": {"timeout": 2, "max_intents": 1},
            "explore": {"timeout": 2, "conclude_timeout": 2},
        },
        "container": {"image": "unused", "network_mode": "host", "completed_action": "stop"},
        "workers": [
            {"name": "reason-ok", "type": "mock", "task_types": ["reason"], "max_running": 1, "priority": 0, "env": {}},
            {"name": "explore-bad", "type": "mock", "task_types": ["explore"], "max_running": 1, "priority": 0, "env": {}},
        ],
    })
    results = [
        StartupHealthcheckResult("reason-ok", True, 0, 1, "200", "ok", "", "mock reason"),
        StartupHealthcheckResult("explore-bad", False, 1, 1, "500", "", "fail", "mock explore"),
    ]

    assert missing_healthy_task_types(config, results) == ["explore"]
