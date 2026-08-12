from __future__ import annotations

import json
import logging
import time

from skidc.dispatcher.config import DispatchConfig, WorkerConfig
from skidc.dispatcher.contracts import parse_json_output, validate_verify_payload
from skidc.dispatcher.prompting import (
    format_dispatch_graph,
    format_scope_constraints,
    load_prompt,
    render_prompt,
)
from skidc.dispatcher.protocol.client import SkidcClient
from skidc.dispatcher.runtime.cancellation import TaskCancellation
from skidc.dispatcher.runtime.containers import ContainerManager
from skidc.dispatcher.runtime.heartbeat import HeartbeatLease
from skidc.dispatcher.tasks.common import (
    best_effort_release,
    cancel_reason,
    did_timeout,
    format_worker_input,
    prepare_android_bridge,
    preview,
    run_worker_process,
    save_task_log,
    write_conclude_result,
    write_graph_snapshot_reference,
)
from skidc.dispatcher.workers.registry import get_driver
from skidc.server.models import Fact, Intent, ProjectDetail

LOG = logging.getLogger(__name__)


def is_verify_intent(intent: Intent) -> bool:
    action = str(intent.action_kind or "").strip().casefold().replace("-", "_")
    return action == "verify" or action.startswith("verify_") or action.startswith("verification")


def _terminal_verify_result(
    attempt_records: list[dict[str, object]],
    required_negative_attempts: int,
) -> str | None:
    if any(record.get("result") == "reproduced" for record in attempt_records):
        return "reproduced"
    valid_negative_count = sum(
        1 for record in attempt_records if record.get("result") == "not_reproduced"
    )
    if valid_negative_count >= required_negative_attempts:
        return "not_reproduced"
    return None


def run_verify_task(
    config: DispatchConfig,
    client: SkidcClient,
    container_manager: ContainerManager,
    project: ProjectDetail,
    export_yaml: str,
    intent: Intent,
    worker: WorkerConfig,
    cancellation: TaskCancellation,
) -> str:
    """Run a bounded, independent reproduction loop for one candidate Fact."""
    candidate = _candidate_fact(project, intent)
    if candidate is None:
        LOG.warning(
            "verify intent has no candidate Fact project=%s intent=%s",
            project.project.id,
            intent.id,
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"

    driver = get_driver(worker.type)
    container_name = container_manager.ensure_running(project.project.id)
    lease = HeartbeatLease.for_intent(
        client,
        project.project.id,
        intent.id,
        worker.name,
        config.runtime.interval,
    )
    lease.start()
    started = time.perf_counter()
    attempt_records: list[dict[str, object]] = []
    evidence_refs: list[str] = []

    try:
        bridge_ready = prepare_android_bridge(
            config, container_manager, container_name, worker,
            lease=lease, cancellation=cancellation,
        )
        if bridge_ready is not None and bridge_ready.returncode != 0:
            LOG.warning(
                "Android Bridge unavailable project=%s intent=%s worker=%s",
                project.project.id, intent.id, worker.name,
            )
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "cancelled" if cancel_reason(bridge_ready, cancellation) else "dependency_unavailable"

        for attempt_number in range(1, config.tasks.verify.max_attempts + 1):
            if cancellation.is_cancelled:
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "cancelled"
            if lease.failure is not None:
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "failed"

            prompt = render_prompt(
                load_prompt(config.runtime.prompt_group, "verify.md"),
                {
                    "graph_yaml": write_graph_snapshot_reference(
                        container_manager,
                        container_name,
                        format_dispatch_graph(project)
                        if project.project.planning_version >= 3
                        else export_yaml.strip(),
                        phase=f"verify_execute_attempt_{attempt_number}",
                    ),
                    "intent_id": intent.id,
                    "intent_description": intent.description,
                    "candidate_fact": json.dumps(
                        candidate.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
                    ),
                    "attempt_number": str(attempt_number),
                    "max_attempts": str(config.tasks.verify.max_attempts),
                    "previous_attempts": json.dumps(
                        attempt_records, ensure_ascii=False, sort_keys=True
                    ),
                    "scope_constraints": format_scope_constraints(project),
                },
            )

            # Every reproduction attempt receives a fresh agent session.
            command = driver.build_execute(worker, prompt, driver.prepare_session())
            attempt_started = time.perf_counter()
            process = run_worker_process(
                container_manager,
                container_name,
                worker,
                command.argv,
                phase=f"verify_execute_attempt_{attempt_number}",
                timeout_seconds=config.tasks.verify.timeout,
                lease=lease,
                cancellation=cancellation,
            )
            attempt_ms = int((time.perf_counter() - attempt_started) * 1000)
            task_log_id = save_task_log(
                client,
                project.project.id,
                "verify",
                worker.name,
                f"verify_execute_attempt_{attempt_number}",
                process,
                attempt_ms,
                intent_id=intent.id,
                stdin=format_worker_input(
                    prompt,
                    command.argv,
                    task_type="verify",
                    phase=f"verify_execute_attempt_{attempt_number}",
                    worker_name=worker.name,
                    operation="independently reproduce one candidate security finding",
                    project_id=project.project.id,
                    intent_id=intent.id,
                    intent_description=intent.description,
                    target=intent.target,
                    port=intent.port,
                    surface_type=intent.surface_type,
                    action_kind=intent.action_kind,
                    priority=intent.priority,
                    suggested_tools=intent.suggested_tools,
                    timeout_seconds=config.tasks.verify.timeout,
                ),
            )
            if task_log_id:
                task_log_ref = f"task_log:{task_log_id}"
                if task_log_ref not in evidence_refs:
                    evidence_refs.append(task_log_ref)

            cancelled = cancel_reason(process, cancellation)
            if cancelled is not None:
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "cancelled"
            if lease.failure is not None:
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "failed"
            if did_timeout(process) or process.returncode != 0:
                attempt_records.append(
                    {
                        "attempt": attempt_number,
                        "result": "runtime_failure",
                        "description": (
                            "worker timeout" if did_timeout(process)
                            else f"worker command failed with code {process.returncode}"
                        ),
                    }
                )
                continue

            try:
                model_output = driver.extract_response_text(process.stdout, process.stderr)
                result, data = validate_verify_payload(parse_json_output(model_output))
            except Exception as exc:
                LOG.info(
                    "verify attempt output rejected project=%s intent=%s attempt=%s error=%s stdout=%s",
                    project.project.id,
                    intent.id,
                    attempt_number,
                    exc,
                    preview(process.stdout),
                )
                attempt_records.append(
                    {
                        "attempt": attempt_number,
                        "result": "invalid_output",
                        "description": f"invalid Verify output: {exc}",
                    }
                )
                continue

            for evidence_ref in data.get("evidence_refs", []):
                if evidence_ref not in evidence_refs:
                    evidence_refs.append(evidence_ref)
            attempt_records.append(
                {
                    "attempt": attempt_number,
                    "result": result,
                    "description": data["description"],
                }
            )
        final_result = _terminal_verify_result(
            attempt_records,
            required_negative_attempts=config.tasks.verify.max_attempts,
        )
        if final_result is None:
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "failed"
        if final_result == "reproduced":
            reproduced_attempts = [
                record for record in attempt_records if record["result"] == "reproduced"
            ]
            last_description = str(reproduced_attempts[-1]["description"])
            description = (
                f"The candidate security impact was reproduced in "
                f"{len(reproduced_attempts)} of {config.tasks.verify.max_attempts} "
                f"independent attempts. Last successful observation: {last_description}"
            )
        else:
            negative_attempts = [
                record for record in attempt_records if record["result"] == "not_reproduced"
            ]
            last_description = str(negative_attempts[-1]["description"])
            description = (
                f"Three independent attempts did not reproduce the candidate finding. "
                f"Last observation: {last_description}"
            )
        return _conclude_verify(
            client,
            project,
            intent,
            candidate,
            worker,
            final_result,
            description,
            attempt_records,
            evidence_refs,
            started,
        )
    except Exception:
        LOG.exception(
            "verify task crashed project=%s intent=%s worker=%s",
            project.project.id,
            intent.id,
            worker.name,
        )
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    finally:
        lease.stop()


def _candidate_fact(project: ProjectDetail, intent: Intent) -> Fact | None:
    source_ids = set(intent.from_) - {"origin", "goal"}
    return next(
        (fact for fact in reversed(project.facts) if fact.id in source_ids),
        None,
    )


def _conclude_verify(
    client: SkidcClient,
    project: ProjectDetail,
    intent: Intent,
    candidate: Fact,
    worker: WorkerConfig,
    result: str,
    description: str,
    attempts: list[dict[str, object]],
    evidence_refs: list[str],
    started: float,
) -> str:
    total_ms = int((time.perf_counter() - started) * 1000)
    return write_conclude_result(
        client,
        project.project.id,
        intent.id,
        worker.name,
        description,
        source="verify_execute",
        phase_ms=total_ms,
        total_ms=total_ms,
        fact_fields={
            "status": result,
            "verification_of": candidate.id,
            "parent_fact": candidate.id,
            "kind": "verification_result",
            "summary": description[:320],
            "subject": {"candidate_fact_id": candidate.id},
            "data": {"result": result, "attempts": attempts},
            "parent_fact_ids": list(intent.from_),
            "evidence_refs": evidence_refs,
            "coverage_refs": list(intent.coverage_refs),
            "confidence": 1.0,
            "created_by": worker.name,
        },
    )
