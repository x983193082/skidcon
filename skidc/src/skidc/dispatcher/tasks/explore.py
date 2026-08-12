from __future__ import annotations

import json
import logging
import time

from skidc.dispatcher.config import DispatchConfig, WorkerConfig
from skidc.dispatcher.coverage_profile import normalize_surface_entry
from skidc.dispatcher.contracts import parse_json_output, validate_explore_payload
from skidc.dispatcher.prompting import format_dispatch_graph, format_intent_coverage, format_scope_constraints, load_prompt, render_prompt
from skidc.planning import is_surface_mapping_intent
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
    project_allows_conclude_fallback,
    preview,
    run_healthcheck,
    run_worker_process,
    save_task_log,
    task_healthcheck_enabled,
    write_conclude_result_with_fact_id,
    write_graph_snapshot_reference,
)
from skidc.dispatcher.workers.registry import get_driver
from skidc.server.models import Intent, ProjectDetail

LOG = logging.getLogger(__name__)


_WEB_FACT_OUTPUT_RULES = '''# Web Fact Output Rules
- Start description with one direct sentence stating the objective outcome or observed security effect. If authentication or a privileged session succeeded, say that first.
- After the outcome, add only the minimum target, method/input, response behavior, and reproduction detail needed to understand this Intent.
- Record only the latest incremental conclusion from the current Intent. Do not mix unrelated pages or mechanisms into this Fact.
- CAPTCHA handling capability and successful authenticated or privileged sessions are separate milestone Facts. When the current Intent establishes either one, conclude it immediately instead of continuing into unrelated authenticated pages.
- Preserve reusable authentication artifacts inside the project container and name their path in the Fact; keep the Cookie, response, and redirect evidence in the attached task log.
- Keep raw requests, responses, cookies, timing samples, and tool output in the current task log or execution artifact; the server attaches those records to the Fact as evidence.
- For a security_test Intent, include `tested_surface_refs` with only the assigned Surfaces actually tested. If a concrete candidate impact was observed, include `verify` with one independent claim per candidate and its Surface refs.
- A surface_mapping Intent records Surfaces only. It does not label them tested and does not request Verify.
- `verify` is only a handoff to the Verify Agent. Do not label the candidate reproduced or not_reproduced yourself.
- An incomplete, timed-out, or failed test is no_result, never a negative security conclusion.
'''


def _with_web_fact_output_rules(
    prompt: str,
    project: ProjectDetail,
    prompt_group: str = 'default',
) -> str:
    if project.project.mode != 'real_website' or prompt_group == 'mock':
        return prompt
    return f'{prompt.rstrip()}\n\n{_WEB_FACT_OUTPUT_RULES}'


def _validate_explore_result(
    payload: dict,
    project: ProjectDetail,
    intent: Intent,
) -> tuple[str, dict | None]:
    real_web = project.project.mode == "real_website"
    result = validate_explore_payload(
        payload,
        fact_only=real_web,
        allow_surfaces=real_web and is_surface_mapping_intent(
            intent.action_kind, intent.test_variant,
        ),
        action_kind=intent.action_kind if real_web else None,
    )
    kind, data = result
    if not real_web or kind != "fact" or data is None:
        return result

    mapping = is_surface_mapping_intent(intent.action_kind, intent.test_variant)
    assigned = list(dict.fromkeys([
        *intent.surface_refs,
        *([intent.surface_ref] if intent.surface_ref else []),
    ]))
    tested = list(data.get("tested_surface_refs") or [])
    verify_requests = list(data.get("verify_requests") or [])
    if mapping:
        if tested or verify_requests:
            raise ValueError("surface_mapping may not mark Surfaces tested or request Verify")
        return result

    # Only the new structured Web protocol promises an exact Surface binding.
    # Legacy rows may have arbitrary action labels and no Surface index entry;
    # keep them executable, while all newly generated Reason work is validated
    # as the canonical security_test action in contracts.py.
    if str(intent.action_kind or "").strip().casefold() != "security_test":
        return result

    if tested:
        if not assigned:
            raise ValueError("security_test tested Surface refs require an assignment")
        unexpected = [surface_id for surface_id in tested if surface_id not in assigned]
        if unexpected:
            raise ValueError(f"tested_surface_refs were not assigned: {', '.join(unexpected)}")
    for request in verify_requests:
        request_refs = list(request.get("surface_refs") or [])
        if not tested or not request_refs or any(
            surface_id not in tested for surface_id in request_refs
        ):
            raise ValueError("Verify candidates must reference explicitly tested Surfaces")
    return kind, data


def run_explore_task(
    config: DispatchConfig,
    client: SkidcClient,
    container_manager: ContainerManager,
    project: ProjectDetail,
    export_yaml: str,
    intent: Intent,
    worker: WorkerConfig,
    cancellation: TaskCancellation,
) -> str:
    driver = get_driver(worker.type)
    task_started = time.perf_counter()
    healthcheck_timeout = config.runtime.healthcheck_timeout
    lease = HeartbeatLease.for_intent(client, project.project.id, intent.id, worker.name, config.runtime.interval)
    lease.start()
    try:
        container_name = container_manager.ensure_running(project.project.id)

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

        if task_healthcheck_enabled(config):
            healthcheck = run_healthcheck(
                container_manager, container_name, worker, driver.build_healthcheck(worker),
                timeout_seconds=healthcheck_timeout, lease=lease, cancellation=cancellation,
            )
            cancelled = cancel_reason(healthcheck.result, cancellation)
            if cancelled is not None:
                LOG.info("explore cancelled during healthcheck project=%s intent=%s worker=%s reason=%s", project.project.id, intent.id, worker.name, cancelled)
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "cancelled"
            if lease.failure is not None:
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "failed"
            if healthcheck.result.returncode != 0:
                LOG.warning("worker unhealthy project=%s intent=%s worker=%s healthcheck_ms=%s stderr=%s", project.project.id, intent.id, worker.name, healthcheck.duration_ms, preview(healthcheck.result.stderr))
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "unhealthy"

        if intent.execution_status == "succeeded" and intent.execution_artifact_ref:
            return _resume_conclusion_from_artifact(
                config,
                client,
                container_manager,
                container_name,
                worker,
                driver,
                project,
                intent,
                export_yaml,
                lease,
                cancellation,
            )

        prompt = render_prompt(
            load_prompt(config.runtime.prompt_group, "explore.md"),
            {
                "graph_yaml": write_graph_snapshot_reference(
                    container_manager, container_name,
                    format_dispatch_graph(project) if project.project.planning_version >= 3 else export_yaml.strip(),
                    phase="explore_execute",
                ),
                "intent_id": intent.id,
                "intent_description": intent.description,
                "intent_action_kind": intent.action_kind or "",
                "intent_surface_refs": ", ".join(intent.surface_refs or ([intent.surface_ref] if intent.surface_ref else [])) or "none",
                "scope_constraints": format_scope_constraints(project),
                "intent_coverage": format_intent_coverage(project, intent.id),
            },
        )
        prompt = _with_web_fact_output_rules(
            prompt, project, config.runtime.prompt_group,
        )

        session = driver.prepare_session()
        execute = driver.build_execute(worker, prompt, session)
        session = execute.session
        execute_started = time.perf_counter()
        first = run_worker_process(
            container_manager, container_name, worker, execute.argv,
            phase="explore_execute", timeout_seconds=config.tasks.explore.timeout,
            lease=lease, cancellation=cancellation,
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        execution_log_id = save_task_log(
            client, project.project.id, "explore", worker.name, "explore_execute",
            first, execute_ms, intent_id=intent.id,
            stdin=format_worker_input(
                prompt,
                execute.argv,
                task_type="explore",
                phase="explore_execute",
                worker_name=worker.name,
                operation="explore assigned intent",
                project_id=project.project.id,
                intent_id=intent.id,
                intent_description=intent.description,
                target=intent.target,
                port=intent.port,
                surface_type=intent.surface_type,
                action_kind=intent.action_kind,
                priority=intent.priority,
                suggested_tools=intent.suggested_tools,
                timeout_seconds=config.tasks.explore.timeout,
            ),
        )
        session = driver.extract_session(session, first.stdout, first.stderr)
        cancelled = cancel_reason(first, cancellation)
        if cancelled is not None:
            LOG.info("explore cancelled project=%s intent=%s worker=%s reason=%s execute_ms=%s", project.project.id, intent.id, worker.name, cancelled, execute_ms)
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "cancelled"
        if lease.failure is not None:
            best_effort_release(client, project.project.id, intent.id, worker.name)
            return "failed"
        if not did_timeout(first) and first.returncode == 0:
            if execution_log_id:
                client.record_execution_success(
                    project.project.id, intent.id, worker.name, execution_log_id
                )
            try:
                model_output = driver.extract_response_text(first.stdout, first.stderr)
                payload = parse_json_output(model_output)
                kind, data = _validate_explore_result(payload, project, intent)
            except Exception as exc:
                LOG.warning("explore parse failed project=%s intent=%s worker=%s error=%s execute_ms=%s stdout=%s stderr=%s", project.project.id, intent.id, worker.name, exc, execute_ms, preview(first.stdout), preview(first.stderr))
                return _try_conclude_fallback(
                    config, client, container_manager, container_name, worker, driver,
                    project, intent, export_yaml, session, lease, cancellation,
                    execution_succeeded=True, previous_error=str(exc),
                )
            if kind in {"rejected", "no_result"}:
                LOG.info("explore produced no committable result project=%s intent=%s worker=%s kind=%s execute_ms=%s", project.project.id, intent.id, worker.name, kind, execute_ms)
                best_effort_release(client, project.project.id, intent.id, worker.name)
                return "rejected" if kind == "rejected" else "failed"
            return _write_explore_conclusion(
                client, project, intent, worker, data,
                source="explore_execute", phase_ms=execute_ms,
                total_ms=int((time.perf_counter() - task_started) * 1000),
            )
        if did_timeout(first):
            LOG.warning("explore timed out project=%s intent=%s worker=%s execute_ms=%s stdout=%s stderr=%s", project.project.id, intent.id, worker.name, execute_ms, preview(first.stdout), preview(first.stderr))
            return _try_conclude_fallback(
                config, client, container_manager, container_name, worker, driver,
                project, intent, export_yaml, session, lease, cancellation,
                execution_succeeded=False,
            )
        LOG.warning("explore command failed project=%s intent=%s worker=%s code=%s execute_ms=%s stdout=%s stderr=%s", project.project.id, intent.id, worker.name, first.returncode, execute_ms, preview(first.stdout), preview(first.stderr))
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    except Exception:
        LOG.exception("explore task crashed project=%s intent=%s worker=%s", project.project.id, intent.id, worker.name)
        best_effort_release(client, project.project.id, intent.id, worker.name)
        return "failed"
    finally:
        lease.stop()


def _resume_conclusion_from_artifact(
    config: DispatchConfig,
    client: SkidcClient,
    container_manager: ContainerManager,
    container_name: str,
    worker: WorkerConfig,
    driver,
    project: ProjectDetail,
    intent: Intent,
    export_yaml: str,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
) -> str:
    """Resume parse/commit without repeating the target-side scan."""
    project_id = project.project.id
    ref = intent.execution_artifact_ref or ""
    if not ref.startswith("task_log:"):
        client.record_conclusion_failure(
            project_id, intent.id, worker.name, "Unsupported execution artifact reference"
        )
        return "success"
    log_id = ref.split(":", 1)[1]
    try:
        artifact = client.get_task_log(project_id, log_id)
    except Exception as exc:
        LOG.warning(
            "execution artifact unavailable project=%s intent=%s log=%s error=%s",
            project_id, intent.id, log_id, exc,
        )
        client.record_conclusion_failure(
            project_id, intent.id, worker.name, f"Execution artifact unavailable: {exc}"
        )
        return "success"

    try:
        model_output = driver.extract_response_text(artifact.stdout or "", artifact.stderr or "")
        payload = parse_json_output(model_output)
        kind, data = _validate_explore_result(payload, project, intent)
        if kind == "fact":
            return _write_explore_conclusion(
                client, project, intent, worker, data,
                source="stored_execution_artifact", phase_ms=0,
            )
    except Exception as exc:
        LOG.info(
            "stored artifact needs conclusion-only pass project=%s intent=%s error=%s",
            project_id, intent.id, exc,
        )

    if cancellation.is_cancelled or lease.failure is not None:
        best_effort_release(client, project_id, intent.id, worker.name)
        return "cancelled" if cancellation.is_cancelled else "failed"

    artifact_text = "\n".join(
        part for part in (
            (artifact.stdout or "")[-24000:],
            (artifact.stderr or "")[-8000:],
        )
        if part
    )
    base_prompt = render_prompt(
        load_prompt(config.runtime.prompt_group, "explore_conclude.md"),
        {
            "graph_yaml": write_graph_snapshot_reference(
                container_manager, container_name,
                format_dispatch_graph(project) if project.project.planning_version >= 3 else export_yaml.strip(),
                phase="explore_conclude_resume",
            ),
            "intent_id": intent.id,
            "intent_description": intent.description,
            "intent_action_kind": intent.action_kind or "",
            "intent_surface_refs": ", ".join(intent.surface_refs or ([intent.surface_ref] if intent.surface_ref else [])) or "none",
            "scope_constraints": format_scope_constraints(project),
            "intent_coverage": format_intent_coverage(project, intent.id),
        },
    )
    base_prompt = _with_web_fact_output_rules(
        base_prompt, project, config.runtime.prompt_group,
    )
    prompt = _extend_prompt_context(
        base_prompt,
        stored_execution_artifact=artifact_text,
        previous_validation_error=(
            intent.conclusion_last_error
            or "The stored output did not match the required JSON contract."
        ),
        instruction=(
            "The target-side execution already succeeded. Do not run target commands "
            "or repeat the scan; convert only the stored artifact into conclusion JSON."
        ),
    )
    command = driver.build_execute(worker, prompt, driver.prepare_session())
    started = time.perf_counter()
    result = run_worker_process(
        container_manager, container_name, worker, command.argv,
        phase="explore_conclude_resume",
        timeout_seconds=config.tasks.explore.conclude_timeout,
        lease=lease,
        cancellation=cancellation,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    save_task_log(
        client, project_id, "explore", worker.name, "explore_conclude_resume",
        result, duration_ms, intent_id=intent.id,
        stdin=format_worker_input(
            prompt, command.argv, task_type="explore", phase="explore_conclude_resume",
            worker_name=worker.name, operation="conclude from stored execution artifact",
            project_id=project_id, intent_id=intent.id,
            intent_description=intent.description,
            timeout_seconds=config.tasks.explore.conclude_timeout,
        ),
    )
    try:
        if result.timed_out or result.returncode != 0:
            raise RuntimeError(
                f"conclusion-only worker failed code={result.returncode} timed_out={result.timed_out}"
            )
        model_output = driver.extract_response_text(result.stdout, result.stderr)
        payload = parse_json_output(model_output)
        kind, data = _validate_explore_result(payload, project, intent)
        if kind != "fact":
            raise RuntimeError(f"conclusion-only worker returned {kind}")
    except Exception as exc:
        LOG.warning(
            "conclusion-only pass failed project=%s intent=%s error=%s",
            project_id, intent.id, exc,
        )
        client.record_conclusion_failure(project_id, intent.id, worker.name, str(exc))
        return "success"
    return _write_explore_conclusion(
        client, project, intent, worker, data,
        source="explore_conclude_resume", phase_ms=duration_ms,
    )


def _try_conclude_fallback(
    config: DispatchConfig,
    client: SkidcClient,
    container_manager: ContainerManager,
    container_name: str,
    worker: WorkerConfig,
    driver,
    project: ProjectDetail,
    intent: Intent,
    export_yaml: str,
    session: str | None,
    lease: HeartbeatLease,
    cancellation: TaskCancellation,
    *,
    execution_succeeded: bool,
    previous_error: str | None = None,
) -> str:
    project_id = project.project.id
    def conclusion_failed(error: str) -> str:
        if execution_succeeded:
            client.record_conclusion_failure(
                project_id, intent.id, worker.name, error,
            )
            return "success"
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"

    if not driver.supports_conclude() or not session:
        LOG.info("conclude fallback unavailable project=%s intent=%s worker=%s supports_conclude=%s has_session=%s", project_id, intent.id, worker.name, driver.supports_conclude(), bool(session))
        return conclusion_failed("conclusion fallback is unavailable")
    if lease.failure is not None:
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"
    if cancellation.is_cancelled:
        LOG.info("conclude fallback skipped because task was cancelled project=%s intent=%s worker=%s reason=%s", project_id, intent.id, worker.name, cancellation.reason)
        best_effort_release(client, project_id, intent.id, worker.name)
        return "cancelled"

    if not project_allows_conclude_fallback(client, project_id, worker_name=worker.name, intent_id=intent.id):
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"

    container_name = container_manager.ensure_running(project_id)

    bridge_ready = prepare_android_bridge(
        config, container_manager, container_name, worker,
        lease=lease, cancellation=cancellation,
    )
    if bridge_ready is not None and bridge_ready.returncode != 0:
        LOG.warning(
            "Android Bridge unavailable before explore conclusion project=%s intent=%s worker=%s",
            project_id, intent.id, worker.name,
        )
        return conclusion_failed("Android Bridge readiness check failed")

    prompt = render_prompt(
        load_prompt(config.runtime.prompt_group, "explore_conclude.md"),
        {
            "graph_yaml": write_graph_snapshot_reference(
                container_manager, container_name,
                format_dispatch_graph(project) if project.project.planning_version >= 3 else export_yaml.strip(),
                phase="explore_conclude",
            ),
            "intent_id": intent.id,
            "intent_description": intent.description,
            "intent_action_kind": intent.action_kind or "",
            "intent_surface_refs": ", ".join(intent.surface_refs or ([intent.surface_ref] if intent.surface_ref else [])) or "none",
            "scope_constraints": format_scope_constraints(project),
            "intent_coverage": format_intent_coverage(project, intent.id),
        },
    )
    prompt = _with_web_fact_output_rules(
        prompt, project, config.runtime.prompt_group,
    )
    if previous_error:
        prompt = _extend_prompt_context(
            prompt, previous_validation_error=previous_error,
        )
    conclude_argv = driver.build_conclude(worker, prompt, session)
    LOG.info("starting conclude fallback project=%s intent=%s worker=%s", project_id, intent.id, worker.name)
    conclude_started = time.perf_counter()
    result = run_worker_process(
        container_manager, container_name, worker, conclude_argv,
        phase="explore_conclude", timeout_seconds=config.tasks.explore.conclude_timeout,
        lease=lease, cancellation=cancellation,
    )
    conclude_ms = int((time.perf_counter() - conclude_started) * 1000)
    save_task_log(
        client, project_id, "explore", worker.name, "explore_conclude",
        result, conclude_ms, intent_id=intent.id,
        stdin=format_worker_input(
            prompt,
            conclude_argv,
            task_type="explore",
            phase="explore_conclude",
            worker_name=worker.name,
            operation="summarize assigned intent after execute fallback",
            project_id=project_id,
            intent_id=intent.id,
            intent_description=intent.description,
            target=intent.target,
            port=intent.port,
            surface_type=intent.surface_type,
            action_kind=intent.action_kind,
            priority=intent.priority,
            suggested_tools=intent.suggested_tools,
            timeout_seconds=config.tasks.explore.conclude_timeout,
        ),
    )
    cancelled = cancel_reason(result, cancellation)
    if cancelled is not None:
        LOG.info("conclude cancelled project=%s intent=%s worker=%s reason=%s conclude_ms=%s", project_id, intent.id, worker.name, cancelled, conclude_ms)
        best_effort_release(client, project_id, intent.id, worker.name)
        return "cancelled"
    if lease.failure is not None:
        best_effort_release(client, project_id, intent.id, worker.name)
        return "failed"
    if result.timed_out or result.returncode != 0:
        LOG.warning("conclude failed project=%s intent=%s worker=%s code=%s timed_out=%s conclude_ms=%s stdout=%s stderr=%s", project_id, intent.id, worker.name, result.returncode, result.timed_out, conclude_ms, preview(result.stdout), preview(result.stderr))
        return conclusion_failed(
            f"conclusion worker failed code={result.returncode} timed_out={result.timed_out}"
        )
    try:
        model_output = driver.extract_response_text(result.stdout, result.stderr)
        payload = parse_json_output(model_output)
        kind, data = _validate_explore_result(payload, project, intent)
    except Exception as exc:
        LOG.warning("conclude parse failed project=%s intent=%s worker=%s error=%s conclude_ms=%s stdout=%s stderr=%s", project_id, intent.id, worker.name, exc, conclude_ms, preview(result.stdout), preview(result.stderr))
        return conclusion_failed(str(exc))
    if kind in {"rejected", "no_result"}:
        LOG.info("conclude produced no committable result project=%s intent=%s worker=%s kind=%s conclude_ms=%s", project_id, intent.id, worker.name, kind, conclude_ms)
        if execution_succeeded:
            return conclusion_failed(f"conclusion worker returned {kind}")
        best_effort_release(client, project_id, intent.id, worker.name)
        return "rejected" if kind == "rejected" else "failed"
    return _write_explore_conclusion(
        client, project, intent, worker, data,
        source="explore_conclude", phase_ms=conclude_ms,
    )


def _extend_prompt_context(prompt: str, **context: str) -> str:
    """Add retry context without corrupting JSON-backed worker prompts."""
    try:
        payload = json.loads(prompt)
    except (TypeError, json.JSONDecodeError):
        additions = "\n\n".join(
            f"{key.replace('_', ' ').title()}:\n{value}"
            for key, value in context.items() if value
        )
        return f"{prompt}\n\n{additions}" if additions else prompt
    if not isinstance(payload, dict):
        return prompt
    payload.update({key: value for key, value in context.items() if value})
    return json.dumps(payload, ensure_ascii=False)


def _write_explore_conclusion(
    client: SkidcClient,
    project: ProjectDetail,
    intent: Intent,
    worker: WorkerConfig,
    data: dict,
    *,
    source: str,
    phase_ms: int,
    total_ms: int | None = None,
) -> str:
    """Commit the Fact first, then deterministically enqueue its Verify work."""
    result = write_conclude_result_with_fact_id(
        client,
        project.project.id,
        intent.id,
        worker.name,
        data["description"],
        source=source,
        phase_ms=phase_ms,
        total_ms=total_ms,
        fact_fields=_normalize_observed_surfaces(project, data),
    )
    verify_requests = data.get("verify_requests")
    if (
        result.status != "success"
        or not result.fact_id
        or project.project.mode != "real_website"
        or not isinstance(verify_requests, list)
    ):
        return result.status
    for verify_request in verify_requests:
        if not isinstance(verify_request, dict):
            continue
        request_refs = [
            str(item) for item in verify_request.get("surface_refs", []) if str(item)
        ]
        response = client.create_intent(
            project.project.id,
            [result.fact_id],
            str(verify_request.get("claim") or "").strip(),
            worker.name,
            target=intent.target,
            port=intent.port,
            path=intent.path,
            surface_type=intent.surface_type,
            surface_ref=request_refs[0] if request_refs else None,
            surface_refs=request_refs,
            action_kind="verify",
            test_variant=intent.test_variant,
            priority=intent.priority,
            suggested_tools=list(intent.suggested_tools),
            coverage_refs=list(intent.coverage_refs),
        )
        if not response.ok:
            LOG.warning(
                "candidate Fact committed but Verify enqueue failed project=%s fact=%s status=%s body=%s",
                project.project.id,
                result.fact_id,
                response.status_code,
                response.text,
            )
    return result.status

def _normalize_observed_surfaces(project: ProjectDetail, data: dict) -> dict:
    normalized = dict(data)
    verify_requests = normalized.pop("verify_requests", None)
    tested_surface_refs = normalized.pop("tested_surface_refs", None)
    state_check = normalized.pop("state_check", None)
    fact_data = dict(normalized.get("data") or {})
    if isinstance(tested_surface_refs, list):
        fact_data["tested_surface_refs"] = list(tested_surface_refs)
    if isinstance(verify_requests, list) and verify_requests:
        fact_data["verify_requests"] = [dict(item) for item in verify_requests]
        fact_data["verify_request"] = str(verify_requests[0].get("claim") or "")
    if isinstance(state_check, dict):
        fact_data["state_check"] = dict(state_check)
    if fact_data:
        normalized["data"] = fact_data
    raw_surfaces = data.get("observed_surfaces")
    if not isinstance(raw_surfaces, list):
        return normalized
    if project.project.mode == "real_website":
        normalized["observed_surfaces"] = [dict(entry) for entry in raw_surfaces]
        return normalized
    surfaces = []
    for entry in raw_surfaces:
        surface = normalize_surface_entry(entry, support_ports=project.project.scope_policy.support_ports)
        if surface is not None:
            surfaces.append(surface)
    normalized["observed_surfaces"] = surfaces
    return normalized
