"""Unit tests for dispatcher helpers that the end-to-end mock suite does not
exercise in isolation: worker ordering, container archive path-safety, task
cancellation semantics, and the reason re-trigger checkpoint logic.

These mirror the coverage points of Cairn's test_scheduler_logic / test_runtime_logic
but are written fresh against Skidc's own implementation."""

from __future__ import annotations

import pytest

from skidc.dispatcher.config import WorkerConfig
from skidc.dispatcher.models import ReasonCheckpoint
from skidc.dispatcher.runtime.cancellation import TaskCancellation
from skidc.dispatcher.runtime.containers import ContainerManager
from skidc.dispatcher.scheduler.loop import DispatcherLoop
from skidc.dispatcher.scheduler.worker_select import choose_worker
from skidc.server.models import Fact, Hint, Intent, ProjectDetail, ProjectMeta


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


def test_reason_trigger_detects_open_intents_drained_to_zero() -> None:
    loop = _bare_loop()
    loop.reason_checkpoints["proj_001"] = ReasonCheckpoint(
        fact_count=2, hint_count=0, open_intent_count=2
    )
    project = _project(facts=2, hints=0, open_intents=0)
    trigger = loop._reason_trigger(project)
    assert trigger is not None and "open_intents:2->0" in trigger
