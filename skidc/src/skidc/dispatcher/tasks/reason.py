from __future__ import annotations

import logging
import time

from skidc.dispatcher.config import DispatchConfig, WorkerConfig
from skidc.dispatcher.contracts import (
    extract_reason_attack_paths,
    parse_json_output,
    validate_reason_payload,
)
from skidc.dispatcher.prompting import (
    format_fact_ids,
    format_open_intents,
    load_prompt,
    render_prompt,
)
from skidc.dispatcher.protocol.client import SkidcClient
from skidc.dispatcher.runtime.cancellation import TaskCancellation
from skidc.dispatcher.runtime.containers import ContainerManager
from skidc.dispatcher.runtime.heartbeat import HeartbeatLease
from skidc.dispatcher.tasks.common import (
    best_effort_release_reason,
    cancel_reason,
    did_timeout,
    preview,
    run_healthcheck,
    run_worker_process,
    task_healthcheck_enabled,
    write_graph_snapshot_reference,
)
from skidc.dispatcher.workers.registry import get_driver
from skidc.server.models import ProjectDetail

LOG = logging.getLogger(__name__)


def run_reason_task(
    config: DispatchConfig,
    client: SkidcClient,
    container_manager: ContainerManager,
    project: ProjectDetail,
    export_yaml: str,
    worker: WorkerConfig,
    cancellation: TaskCancellation,
) -> str:
    driver = get_driver(worker.type)
    task_started = time.perf_counter()
    healthcheck_timeout = config.runtime.healthcheck_timeout
    lease = HeartbeatLease.for_reason(client, project.project.id, worker.name, config.runtime.interval)
    lease.start()
    try:
        container_name = container_manager.ensure_running(project.project.id)

        if task_healthcheck_enabled(config):
            healthcheck = run_healthcheck(
                container_manager,
                container_name,
                worker,
                driver.build_healthcheck(worker),
                timeout_seconds=healthcheck_timeout,
                lease=lease,
                cancellation=cancellation,
            )
            cancelled = cancel_reason(healthcheck.result, cancellation)
            if cancelled is not None:
                LOG.info("reason cancelled during healthcheck project=%s worker=%s reason=%s", project.project.id, worker.name, cancelled)
                return "cancelled"
            if lease.failure is not None:
                LOG.warning("heartbeat lost during reason healthcheck project=%s worker=%s status=%s", project.project.id, worker.name, lease.failure.status_code)
                return "failed"
            if healthcheck.result.returncode != 0:
                LOG.warning("worker unhealthy project=%s worker=%s healthcheck_ms=%s stderr=%s", project.project.id, worker.name, healthcheck.duration_ms, preview(healthcheck.result.stderr))
                return "unhealthy"

        open_intents = [
            {"id": intent.id, "from": intent.from_, "description": intent.description, "worker": intent.worker}
            for intent in project.intents
            if intent.to is None
        ]
        allowed_fact_ids = [fact.id for fact in project.facts if fact.id != "goal"]
        prompt = render_prompt(
            load_prompt(config.runtime.prompt_group, "reason.md"),
            {
                "graph_yaml": write_graph_snapshot_reference(
                    container_manager, container_name, export_yaml.strip(), phase="reason_execute",
                ),
                "fact_ids": format_fact_ids(allowed_fact_ids),
                "open_intents": format_open_intents(open_intents),
                "max_intents": str(config.tasks.reason.max_intents),
            },
        )

        session = driver.prepare_session()
        command = driver.build_execute(worker, prompt, session)
        execute_started = time.perf_counter()
        result = run_worker_process(
            container_manager,
            container_name,
            worker,
            command.argv,
            phase="reason_execute",
            timeout_seconds=config.tasks.reason.timeout,
            lease=lease,
            cancellation=cancellation,
        )
        execute_ms = int((time.perf_counter() - execute_started) * 1000)
        total_ms = int((time.perf_counter() - task_started) * 1000)
        cancelled = cancel_reason(result, cancellation)
        if cancelled is not None:
            LOG.info("reason cancelled project=%s worker=%s reason=%s execute_ms=%s", project.project.id, worker.name, cancelled, execute_ms)
            return "cancelled"
        if lease.failure is not None:
            LOG.warning("heartbeat lost during reason project=%s worker=%s status=%s execute_ms=%s", project.project.id, worker.name, lease.failure.status_code, execute_ms)
            return "failed"
        if did_timeout(result):
            LOG.warning("reason timed out project=%s worker=%s execute_ms=%s total_ms=%s stdout=%s stderr=%s", project.project.id, worker.name, execute_ms, total_ms, preview(result.stdout), preview(result.stderr))
            return "failed"
        if result.returncode != 0:
            LOG.warning("reason command failed project=%s worker=%s code=%s execute_ms=%s stdout=%s stderr=%s", project.project.id, worker.name, result.returncode, execute_ms, preview(result.stdout), preview(result.stderr))
            return "failed"
        try:
            model_output = driver.extract_response_text(result.stdout, result.stderr)
            payload = parse_json_output(model_output)
            kind, data = validate_reason_payload(
                payload, open_intents_empty=not open_intents, max_intents=config.tasks.reason.max_intents,
            )
        except Exception as exc:
            LOG.warning("reason parse failed project=%s worker=%s error=%s execute_ms=%s stdout=%s stderr=%s", project.project.id, worker.name, exc, execute_ms, preview(result.stdout), preview(result.stderr))
            return "failed"
        if kind == "rejected":
            LOG.warning("reason rejected project=%s worker=%s execute_ms=%s stdout=%s", project.project.id, worker.name, execute_ms, preview(result.stdout))
            return "rejected"
        _create_attack_paths(client, project.project.id, worker.name, extract_reason_attack_paths(payload))
        if kind == "complete":
            response = client.complete(project.project.id, data["from"], data["description"], worker.name)
            if response.status_code == 403:
                LOG.info("project became inactive during reason complete project=%s worker=%s", project.project.id, worker.name)
                return "success"
            if not response.ok:
                LOG.warning("reason complete write failed project=%s worker=%s status=%s body=%s", project.project.id, worker.name, response.status_code, response.text)
                return "failed"
            LOG.info("project completed project=%s worker=%s from=%s execute_ms=%s total_ms=%s", project.project.id, worker.name, data["from"], execute_ms, total_ms)
            return "success"
        if kind == "intents":
            created = 0
            for intent_data in data:
                response = client.create_intent(project.project.id, intent_data["from"], intent_data["description"], worker.name)
                if response.status_code == 403:
                    LOG.info("project became inactive during reason intent create project=%s worker=%s created=%s", project.project.id, worker.name, created)
                    return "success"
                if response.status_code == 409:
                    LOG.info("reason intent lost race project=%s worker=%s from=%s", project.project.id, worker.name, intent_data["from"])
                    continue
                if not response.ok:
                    LOG.warning("reason intent write failed project=%s worker=%s status=%s body=%s", project.project.id, worker.name, response.status_code, response.text)
                    continue
                created += 1
                LOG.info("reason created intent project=%s worker=%s from=%s description=%s", project.project.id, worker.name, intent_data["from"], intent_data["description"])
            LOG.info("reason finished project=%s worker=%s created_intents=%s/%s execute_ms=%s total_ms=%s", project.project.id, worker.name, created, len(data), execute_ms, total_ms)
            if created == 0:
                LOG.warning("reason created no intents project=%s worker=%s attempted=%s", project.project.id, worker.name, len(data))
                return "failed"
            return "success"
        LOG.info("reason finished without graph change project=%s worker=%s execute_ms=%s total_ms=%s", project.project.id, worker.name, execute_ms, total_ms)
        return "success"
    finally:
        lease.stop()
        best_effort_release_reason(client, project.project.id, worker.name)


def _create_attack_paths(client, project_id: str, worker_name: str, paths: list[dict]) -> None:
    """Best-effort: persist any attack paths the reasoner identified. A bad fact ref
    (404) or an inactive project (403) skips that path without failing the reason task —
    attack paths are an annotation layer, never a gate on graph progress."""
    for path in paths:
        response = client.create_attack_path(
            project_id, path["name"], path["fact_chain"], path["description"], path["severity"],
        )
        if response.ok:
            LOG.info("reason created attack_path project=%s worker=%s name=%s chain=%s", project_id, worker_name, path["name"], path["fact_chain"])
        else:
            LOG.info("reason attack_path skipped project=%s worker=%s name=%s status=%s", project_id, worker_name, path["name"], response.status_code)
