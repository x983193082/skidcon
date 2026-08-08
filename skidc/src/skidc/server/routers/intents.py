import hashlib
import json
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from skidc.dispatcher.coverage_profile import normalize_surface_entry
from skidc.planning import is_surface_mapping_intent

from skidc.server.db import get_conn
from skidc.server.models import (
    ConcludeRequest,
    ConcludeResponse,
    CreateIntentRequest,
    ObservedSurfaceRequest,
    Fact,
    HeartbeatRequest,
    Intent,
    RecordIntentConclusionFailureRequest,
    RecordIntentExecutionRequest,
    UpsertSurfaceInventoryRequest,
    TaskFailureRequest,
)
from skidc.server.services import (
    bind_coverage_intent,
    coverage_work_key,
    conclude_intent_with_failure_fact,
    clear_completion_blocked,
    check_project_active,
    derive_recon_fact_fields,
    get_claimable_open_intent_or_404,
    get_releasable_open_intent_or_404,
    fact_to_model,
    intent_to_model,
    mark_intent_failure,
    next_fact_id,
    next_intent_id,
    project_meta_from_row,
    reconcile_fact_coverage,
    reconcile_project_attack_paths,
    upsert_surface_inventory_record,
    utcnow,
    validate_coverage_exists,
    validate_verification_reference,
    validate_facts_exist,
    validate_intent_creator_worker,
    validate_intent_scope,
    validate_goal_not_in_sources,
)

router = APIRouter(tags=["intents"])


def _normalize_web_observed_surface(
    conn,
    project_id: str,
    intent_row,
    project,
    surface: ObservedSurfaceRequest,
) -> UpsertSurfaceInventoryRequest:
    origin_row = conn.execute(
        "SELECT description FROM facts WHERE project_id = ? AND id = 'origin'",
        (project_id,),
    ).fetchone()
    origin = str(origin_row["description"] or "") if origin_row else ""
    target_hint = str(intent_row["target"] or "").strip() or origin
    parsed_target = urlparse(
        target_hint if "://" in target_hint else f"//{target_hint}"
    )
    target = parsed_target.hostname
    if not target and project.scope_policy.allowed_targets:
        target = project.scope_policy.allowed_targets[0]
    port = intent_row["port"] or parsed_target.port
    if port is None and parsed_target.scheme:
        port = 443 if parsed_target.scheme.casefold() == "https" else 80

    raw = surface.model_dump()
    if "://" in surface.path:
        raw["url"] = raw.pop("path")
    else:
        raw["target"] = target
        raw["port"] = port
    normalized = normalize_surface_entry(
        raw,
        support_ports=project.scope_policy.support_ports,
    )
    if normalized is None:
        raise HTTPException(422, "Observed Surface could not be normalized")
    return UpsertSurfaceInventoryRequest(
        **normalized,
        planning_status="assessed",
    )


@router.post(
    "/projects/{project_id}/intents",
    response_model=Intent,
    status_code=201,
)
def create_intent(project_id: str, body: CreateIntentRequest):
    with get_conn() as conn:
        project_row = check_project_active(conn, project_id)
        validate_facts_exist(conn, project_id, body.from_)
        validate_goal_not_in_sources(body.from_)
        validate_intent_creator_worker(body.creator, body.worker)
        validate_coverage_exists(conn, project_id, body.coverage_refs)
        project = project_meta_from_row(project_row)
        requested_action = str(body.action_kind or "").strip()
        surface_refs = list(dict.fromkeys([
            *body.surface_refs,
            *([body.surface_ref] if body.surface_ref else []),
        ]))
        if project.mode == "real_website":
            if not requested_action:
                if project.phase == "recon":
                    action_kind = "surface_mapping"
                else:
                    # Existing API clients predate the structured Reason
                    # contract. New Reason output is strict; retain old rows
                    # as non-mapping work without guessing from prose.
                    action_kind = "legacy_security_test"
            elif _is_verify_action(requested_action):
                action_kind = "verify"
            else:
                action_kind = requested_action.strip().casefold().replace("-", "_")
            if action_kind == "security_test" and not surface_refs:
                raise HTTPException(422, "security_test Intent requires surface_ref or surface_refs")
            if action_kind == "security_test" and project.planning_version >= 3 and len(surface_refs) > 5:
                raise HTTPException(422, "security_test Intent may bind at most 5 related Surfaces")
        else:
            action_kind = body.action_kind
        primary_surface_ref = surface_refs[0] if surface_refs else None
        hypothesis_row = None
        if body.hypothesis_id:
            hypothesis_row = conn.execute(
                "SELECT * FROM hypotheses WHERE project_id = ? AND id = ?",
                (project_id, body.hypothesis_id),
            ).fetchone()
            if hypothesis_row is None:
                raise HTTPException(404, "Hypothesis not found")
            if project.planning_version < 2:
                raise HTTPException(409, "Hypothesis-bound Intents require planning_version 2")
            if hypothesis_row["status"] not in {"candidate", "planned"}:
                raise HTTPException(409, "Hypothesis is not executable")
        requested_variant = body.test_variant
        test_variant = _resolve_test_variant(
            conn, project_id, project.mode, body.coverage_refs, requested_variant,
        )
        work_key = None
        verify_intent = project.mode == "real_website" and action_kind == "verify"
        if verify_intent:
            candidate_ids = sorted(
                fact_id for fact_id in body.from_ if fact_id not in {"origin", "goal"}
            )
            if not candidate_ids:
                raise HTTPException(422, "Verify Intent must reference a candidate Fact")
            identity = "\n".join([*candidate_ids, *surface_refs])
            work_key = "verify:" + hashlib.sha256(identity.encode()).hexdigest()[:24]
            existing_work = conn.execute(
                """SELECT * FROM intents
                   WHERE project_id = ? AND work_key = ? AND status = 'open'""",
                (project_id, work_key),
            ).fetchone()
            if existing_work is not None:
                return intent_to_model(conn, existing_work, project_id)
        elif project.mode == "real_website" and len(body.coverage_refs) == 1:
            coverage_row = conn.execute(
                "SELECT * FROM coverage_items WHERE project_id = ? AND id = ?",
                (project_id, body.coverage_refs[0]),
            ).fetchone()
            assert coverage_row is not None
            work_key = coverage_work_key(
                coverage_row,
                test_variant or action_kind or "general",
                action_kind,
            )
            existing_work = conn.execute(
                """SELECT * FROM intents
                   WHERE project_id = ? AND work_key = ? AND status = 'open'""",
                (project_id, work_key),
            ).fetchone()
            if existing_work is not None:
                return intent_to_model(conn, existing_work, project_id)
        for surface_id in surface_refs:
            surface_row = conn.execute(
                "SELECT id FROM surface_inventory WHERE project_id = ? AND id = ?",
                (project_id, surface_id),
            ).fetchone()
            if surface_row is None:
                raise HTTPException(404, "Surface not found")
        validate_intent_scope(
            project.scope_policy,
            target=body.target,
            port=body.port,
            path=body.path,
            action_kind=requested_action or action_kind,
        )

        now = utcnow()
        iid = next_intent_id(conn, project_id)
        claimed = body.worker is not None
        inserted = conn.execute(
            """
            INSERT OR IGNORE INTO intents (
                id, project_id, to_fact_id, description, creator, worker, last_heartbeat_at, created_at, concluded_at,
                target, port, path, surface_type, surface_ref, surface_refs, action_kind, test_variant, priority, suggested_tools, status, work_key, hypothesis_id
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                iid,
                project_id,
                body.description,
                body.creator,
                body.worker,
                now if claimed else None,
                now,
                body.target,
                body.port,
                body.path,
                body.surface_type,
                primary_surface_ref,
                json.dumps(surface_refs, ensure_ascii=False),
                action_kind,
                test_variant,
                body.priority,
                json.dumps(body.suggested_tools),
                work_key,
                body.hypothesis_id,
            ),
        )
        if inserted.rowcount == 0:
            if not work_key:
                raise HTTPException(409, "Intent identity already exists")
            existing_work = conn.execute(
                """SELECT * FROM intents
                   WHERE project_id = ? AND work_key = ? AND status = 'open'""",
                (project_id, work_key),
            ).fetchone()
            if existing_work is not None:
                return intent_to_model(conn, existing_work, project_id)
            raise HTTPException(409, "Intent work identity already exists")
        for fid in body.from_:
            conn.execute(
                "INSERT INTO intent_sources (intent_id, project_id, fact_id) VALUES (?, ?, ?)",
                (iid, project_id, fid),
            )
        for coverage_id in body.coverage_refs:
            bind_coverage_intent(conn, project_id, coverage_id, iid, created_at=now)
        if hypothesis_row is not None:
            conn.execute(
                """UPDATE hypotheses SET status = 'planned', intent_id = ?,
                   coverage_id = COALESCE(coverage_id, ?), updated_at = ?
                   WHERE project_id = ? AND id = ?""",
                (iid, body.coverage_refs[0] if body.coverage_refs else None, now, project_id, body.hypothesis_id),
            )

        clear_completion_blocked(conn, project_id)
        return Intent(
            id=iid,
            **{"from": body.from_},
            to=None,
            description=body.description,
            creator=body.creator,
            worker=body.worker,
            last_heartbeat_at=now if claimed else None,
            created_at=now,
            concluded_at=None,
            target=body.target,
            port=body.port,
            path=body.path,
            surface_type=body.surface_type,
            surface_ref=primary_surface_ref,
            surface_refs=surface_refs,
            action_kind=action_kind,
            test_variant=test_variant,
            priority=body.priority,
            suggested_tools=body.suggested_tools,
            status="open",
            work_key=work_key,
            coverage_refs=body.coverage_refs,
            hypothesis_id=body.hypothesis_id,
        )


@router.post(
    "/projects/{project_id}/intents/{intent_id}/heartbeat",
    response_model=Intent,
)
def heartbeat(project_id: str, intent_id: str, body: HeartbeatRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        get_claimable_open_intent_or_404(conn, project_id, intent_id, body.worker)

        now = utcnow()
        conn.execute(
            "UPDATE intents SET worker = ?, last_heartbeat_at = ?, execution_status = CASE WHEN execution_status = 'pending' THEN 'running' ELSE execution_status END WHERE id = ? AND project_id = ?",
            (body.worker, now, intent_id, project_id),
        )
        conn.execute(
            """
            UPDATE coverage_items
            SET execution_status = 'testing', status = 'testing', updated_at = ?
            WHERE project_id = ?
              AND id IN (
                  SELECT coverage_id FROM coverage_intents
                  WHERE project_id = ? AND intent_id = ?
              )
              AND execution_status IN ('untested', 'queued', 'testing')
            """,
            (now, project_id, project_id, intent_id),
        )
        conn.execute(
            "UPDATE hypotheses SET status = 'testing', updated_at = ? "
            "WHERE project_id = ? AND intent_id = ? AND status IN ('candidate', 'planned', 'testing')",
            (now, project_id, intent_id),
        )

        updated = conn.execute(
            "SELECT * FROM intents WHERE id = ? AND project_id = ?",
            (intent_id, project_id),
        ).fetchone()
        return intent_to_model(conn, updated, project_id)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/release",
    response_model=Intent,
)
def release(project_id: str, intent_id: str, body: HeartbeatRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        row = get_releasable_open_intent_or_404(conn, project_id, intent_id, body.worker)

        if row["worker"] == body.worker:
            conn.execute(
                "UPDATE intents SET worker = NULL WHERE id = ? AND project_id = ?",
                (intent_id, project_id),
            )
            conn.execute(
                """
                UPDATE coverage_items
                SET execution_status = 'queued', status = 'untested', updated_at = ?
                WHERE project_id = ?
                  AND id IN (
                      SELECT coverage_id FROM coverage_intents
                      WHERE project_id = ? AND intent_id = ?
                  )
                  AND execution_status = 'testing'
                """,
                (utcnow(), project_id, project_id, intent_id),
            )
            row = conn.execute(
                "SELECT * FROM intents WHERE id = ? AND project_id = ?",
                (intent_id, project_id),
            ).fetchone()

        return intent_to_model(conn, row, project_id)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/execution-success",
    response_model=Intent,
)
def record_execution_success(
    project_id: str,
    intent_id: str,
    body: RecordIntentExecutionRequest,
):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        intent = get_claimable_open_intent_or_404(
            conn, project_id, intent_id, body.worker
        )
        task_log = conn.execute(
            """SELECT id FROM task_logs
            WHERE project_id = ? AND id = ? AND intent_id = ?""",
            (project_id, body.task_log_id, intent_id),
        ).fetchone()
        if task_log is None:
            raise HTTPException(404, "Execution task log not found for Intent")
        now = utcnow()
        conn.execute(
            """UPDATE intents SET execution_status = 'succeeded',
               execution_artifact_ref = ?, execution_completed_at = ?,
               conclusion_last_error = NULL
               WHERE project_id = ? AND id = ?""",
            (f"task_log:{body.task_log_id}", now, project_id, intent_id),
        )
        updated = conn.execute(
            "SELECT * FROM intents WHERE project_id = ? AND id = ?",
            (project_id, intent_id),
        ).fetchone()
        return intent_to_model(conn, updated or intent, project_id)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/conclusion-failure",
    response_model=Intent,
)
def record_conclusion_failure(
    project_id: str,
    intent_id: str,
    body: RecordIntentConclusionFailureRequest,
):
    with get_conn() as conn:
        project_row = check_project_active(conn, project_id)
        row = get_claimable_open_intent_or_404(conn, project_id, intent_id, body.worker)
        attempts = int(row["conclusion_attempt_count"] or 0) + 1
        now = utcnow()
        if attempts >= 3:
            conn.execute(
                """UPDATE intents SET conclusion_attempt_count = ?, conclusion_last_error = ?,
                   worker = NULL, last_heartbeat_at = NULL, last_worker = ?, next_retry_at = NULL,
                   failed_at = ?, dead_lettered_at = ?, status = 'dead_lettered'
                   WHERE project_id = ? AND id = ? AND execution_status = 'succeeded'""",
                (attempts, body.error[:2000], body.worker, now, now, project_id, intent_id),
            )
            conn.execute(
                """UPDATE hypotheses SET status = 'inconclusive', last_error = ?, updated_at = ?
                   WHERE project_id = ? AND intent_id = ?
                     AND status NOT IN ('supported', 'refuted', 'waived')""",
                (body.error[:2000], now, project_id, intent_id),
            )
            conn.execute(
                """UPDATE coverage_items SET execution_status = 'blocked', status = 'failed',
                   outcome = NULL, updated_at = ? WHERE project_id = ? AND id IN (
                       SELECT coverage_id FROM coverage_intents
                       WHERE project_id = ? AND intent_id = ?
                   ) AND execution_status <> 'completed'""",
                (now, project_id, project_id, intent_id),
            )
            conclude_intent_with_failure_fact(
                conn,
                project_id,
                intent_id,
                worker=body.worker,
                error=body.error,
                attempt_count=attempts,
                failure_stage="conclusion_failed",
                execution_status="succeeded",
                now=now,
            )
        else:
            conn.execute(
                """UPDATE intents SET conclusion_attempt_count = ?, conclusion_last_error = ?,
                   worker = NULL, last_heartbeat_at = NULL, last_worker = ?, next_retry_at = ?
                   WHERE project_id = ? AND id = ? AND execution_status = 'succeeded'""",
                (
                    attempts,
                    body.error[:2000],
                    body.worker,
                    now,
                    project_id,
                    intent_id,
                ),
            )
        if project_row["mode"] == "real_website" and attempts >= 3:
            conn.execute(
                """UPDATE coverage_items
                   SET execution_status = 'queued', status = 'untested',
                       outcome = NULL, updated_at = ?
                   WHERE project_id = ? AND id IN (
                       SELECT coverage_id FROM coverage_intents
                       WHERE project_id = ? AND intent_id = ?
                   )""",
                (now, project_id, project_id, intent_id),
            )
        updated = conn.execute(
            "SELECT * FROM intents WHERE project_id = ? AND id = ?",
            (project_id, intent_id),
        ).fetchone()
        return intent_to_model(conn, updated, project_id)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/failure",
    response_model=Intent,
)
def record_failure(project_id: str, intent_id: str, body: TaskFailureRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        row = mark_intent_failure(
            conn,
            project_id,
            intent_id,
            worker=body.worker,
            error=body.error,
            max_attempts=body.max_attempts,
            backoff_seconds=body.backoff_seconds,
        )
        return intent_to_model(conn, row, project_id)


@router.post(
    "/projects/{project_id}/intents/{intent_id}/conclude",
    response_model=ConcludeResponse,
)
def conclude(project_id: str, intent_id: str, body: ConcludeRequest):
    with get_conn() as conn:
        project = project_meta_from_row(check_project_active(conn, project_id))
        if project.mode == "real_website" and body.coverage_refs:
            bound_rows = conn.execute(
                """
                SELECT coverage_id FROM coverage_intents
                WHERE project_id = ? AND intent_id = ?
                UNION
                SELECT id FROM coverage_items
                WHERE project_id = ? AND intent_id = ?
                """,
                (project_id, intent_id, project_id, intent_id),
            ).fetchall()
            bound_refs = {row["coverage_id"] for row in bound_rows}
            requested_refs = set(body.coverage_refs)
            if len(requested_refs) > 1 or requested_refs != bound_refs:
                raise HTTPException(
                    409, "Fact coverage_refs must match the real_website Intent Coverage binding"
                )
        intent_row = get_claimable_open_intent_or_404(conn, project_id, intent_id, body.worker)
        intent_variant = str(intent_row["test_variant"] or "").strip()
        action_kind = str(intent_row["action_kind"] or "").strip().casefold()
        verify_intent = project.mode == "real_website" and _is_verify_action(action_kind)
        fact_only = project.mode == "real_website" and not verify_intent
        mapping_intent = is_surface_mapping_intent(
            intent_row["action_kind"], intent_row["test_variant"],
        )
        assigned_surface_refs = list(dict.fromkeys([
            *_stored_json_list(intent_row["surface_refs"] if "surface_refs" in intent_row.keys() else None),
            *([intent_row["surface_ref"]] if intent_row["surface_ref"] else []),
        ]))
        tested_surface_refs = body.data.get("tested_surface_refs", [])
        if project.mode == "real_website":
            if not isinstance(tested_surface_refs, list) or not all(
                isinstance(surface_id, str) and surface_id.strip()
                for surface_id in tested_surface_refs
            ):
                raise HTTPException(422, "tested_surface_refs must contain Surface ids")
            tested_surface_refs = list(dict.fromkeys(
                surface_id.strip() for surface_id in tested_surface_refs
            ))
            if mapping_intent and tested_surface_refs:
                raise HTTPException(409, "surface_mapping cannot mark Surfaces tested")
            if action_kind == "security_test":
                if not tested_surface_refs and len(assigned_surface_refs) == 1:
                    tested_surface_refs = list(assigned_surface_refs)
                    body.data["tested_surface_refs"] = tested_surface_refs
                if not assigned_surface_refs or not tested_surface_refs:
                    raise HTTPException(
                        409, "security_test requires assigned and tested Surface refs"
                    )
                if any(
                    surface_id not in assigned_surface_refs
                    for surface_id in tested_surface_refs
                ):
                    raise HTTPException(
                        409, "tested_surface_refs must be assigned to the Intent"
                    )
        if project.mode == "real_website" and body.observed_surfaces:
            if not mapping_intent:
                raise HTTPException(
                    409, "Only reconnaissance or page-mapping Intents may record Surfaces"
                )
            if any(
                not isinstance(surface, ObservedSurfaceRequest)
                for surface in body.observed_surfaces
            ):
                raise HTTPException(
                    422, "Web Surface observations may contain only method, path, params, auth_context, and surface_type"
                )
        source_rows = conn.execute(
            "SELECT fact_id FROM intent_sources WHERE project_id = ? AND intent_id = ? ORDER BY rowid",
            (project_id, intent_id),
        ).fetchall()
        source_fact_ids = [str(row["fact_id"]) for row in source_rows]
        verification_of = None if fact_only else body.verification_of
        if verify_intent:
            candidates = [
                fact_id for fact_id in source_fact_ids
                if fact_id not in {"origin", "goal"}
            ]
            if not candidates:
                raise HTTPException(409, "Verify Intent must reference a candidate Fact")
            verification_of = candidates[-1]
            if body.verification_of and body.verification_of != verification_of:
                raise HTTPException(
                    409, "Verify result must reference the candidate Fact from its Intent"
                )
            if str(body.status or "").casefold() not in {
                "reproduced", "not_reproduced",
            }:
                raise HTTPException(
                    409, "Verify result must be reproduced or not_reproduced"
                )
        elif verification_of:
            validate_facts_exist(conn, project_id, [verification_of])
        recon_category, recon_executed, recon_found_results = derive_recon_fact_fields(
            intent_row,
            supplied_category=None if fact_only else body.recon_category,
            supplied_executed=None if fact_only else body.recon_executed,
            supplied_found_results=None if fact_only else body.recon_found_results,
            observed_surface_count=len(body.observed_surfaces),
        )
        informational_intent = not fact_only and bool(
            recon_category
            or intent_variant.casefold() == "function_mapping"
            or any(
                marker in action_kind
                for marker in (
                    "recon", "discover", "enumerat", "fingerprint", "crawl",
                    "inventory", "mapping", "port_scan", "directory", "asset",
                )
            )
        )
        if (
            not fact_only
            and not informational_intent
            and intent_variant
            and body.vuln_type
            and intent_variant.casefold() != body.vuln_type.casefold()
        ):
            raise HTTPException(409, "Fact vuln_type must match the Intent test_variant")
        vuln_type = (
            None
            if fact_only or informational_intent or verify_intent
            else (intent_variant or body.vuln_type)
        )
        fact_status = None if fact_only else body.status
        severity = None if fact_only or verify_intent else body.severity
        fact_kind = (
            "verification_result"
            if verify_intent
            else "surface_observation"
            if fact_only and (recon_category or intent_variant.casefold() == "function_mapping")
            else "execution_result" if fact_only else body.kind
        )
        if informational_intent:
            if str(fact_status or "").casefold() in {"confirmed", "verified", "completed"}:
                fact_status = "informational"
            if str(severity or "").casefold() == "info":
                severity = None
            if fact_kind == "legacy_text":
                fact_kind = "surface_observation"

        if not verify_intent:
            validate_verification_reference(
                conn,
                project_id,
                verification_of,
                candidate_variant=vuln_type,
                candidate_status=fact_status,
                candidate_intent_id=intent_id,
            )
        parent_fact_ids = source_fact_ids if project.mode == "real_website" else list(body.parent_fact_ids)
        if not fact_only and body.parent_fact and body.parent_fact not in parent_fact_ids:
            parent_fact_ids.append(body.parent_fact)
        if parent_fact_ids:
            validate_facts_exist(conn, project_id, parent_fact_ids)
        evidence_refs = list(body.evidence_refs)
        if project.mode != "real_website" and body.recon_evidence_ref and body.recon_evidence_ref not in evidence_refs:
            evidence_refs.append(body.recon_evidence_ref)
        task_log_rows = conn.execute(
            "SELECT id FROM task_logs WHERE project_id = ? AND intent_id = ? ORDER BY created_at, id",
            (project_id, intent_id),
        ).fetchall()
        for task_log in task_log_rows:
            evidence_ref = f"task_log:{task_log['id']}"
            if evidence_ref not in evidence_refs:
                evidence_refs.append(evidence_ref)

        now = utcnow()
        fid = next_fact_id(conn, project_id)

        conn.execute(
            """
            INSERT INTO facts (
                id, project_id, description, scope, vuln_type, severity, parent_fact, verification_of, goal_type, status,
                recon_category, recon_executed, recon_found_results, recon_tool, recon_target, recon_evidence_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fid,
                project_id,
                body.description,
                None if project.mode == "real_website" else body.scope,
                vuln_type,
                severity,
                verification_of if verify_intent else (None if fact_only else body.parent_fact),
                verification_of,
                None if project.mode == "real_website" else body.goal_type,
                fact_status,
                recon_category,
                _bool_to_db(recon_executed),
                _bool_to_db(recon_found_results),
                None if project.mode == "real_website" else body.recon_tool,
                None if project.mode == "real_website" else body.recon_target,
                None if project.mode == "real_website" else body.recon_evidence_ref,
            ),
        )
        conn.execute(
            """UPDATE facts SET schema_version = ?, kind = ?, summary = ?,
               subject = ?, data = ?, parent_fact_ids = ?, evidence_refs = ?,
               confidence = ?, created_by = ?, created_at = ?
               WHERE project_id = ? AND id = ?""",
            (
                1 if fact_only else body.schema_version,
                fact_kind,
                body.description[:320] if fact_only else (body.summary or body.description[:320]),
                "{}" if fact_only else json.dumps(body.subject, ensure_ascii=False),
                json.dumps(body.data, ensure_ascii=False),
                json.dumps(parent_fact_ids, ensure_ascii=False),
                json.dumps(evidence_refs, ensure_ascii=False),
                None if fact_only else body.confidence,
                body.worker if fact_only else (body.created_by or body.worker),
                now, project_id, fid,
            ),
        )
        for batch_start in range(0, len(body.observed_surfaces), 100):
            for surface in body.observed_surfaces[batch_start:batch_start + 100]:
                stored_surface = surface
                if project.mode == "real_website":
                    assert isinstance(surface, ObservedSurfaceRequest)
                    stored_surface = _normalize_web_observed_surface(
                        conn, project_id, intent_row, project, surface,
                    )
                elif isinstance(surface, ObservedSurfaceRequest):
                    raise HTTPException(422, "Structured Surface identity is required")
                validate_intent_scope(
                    project.scope_policy,
                    target=stored_surface.target,
                    port=stored_surface.port,
                    path=stored_surface.path_template,
                    action_kind="surface_observation",
                )
                upsert_surface_inventory_record(
                    conn, project_id, stored_surface, source_fact_id=fid,
                )
        conn.execute(
            """
            UPDATE intents
            SET to_fact_id = ?,
                worker = ?,
                last_heartbeat_at = ?,
                concluded_at = ?,
                next_retry_at = NULL,
                dead_lettered_at = NULL,
                status = 'concluded',
                execution_status = 'succeeded',
                commit_status = 'committed'
            WHERE id = ? AND project_id = ?
            """,
            (fid, body.worker, now, now, intent_id, project_id),
        )
        if project.mode == "real_website":
            # Coverage is only an execution ledger in real_website mode. A
            # concluded Intent proves the assigned check ran; it does not let
            # the server classify the Fact as vulnerable or safe.
            conn.execute(
                """UPDATE coverage_items
                   SET execution_status = 'completed', status = 'informational',
                       outcome = 'informational', evidence_ref = ?, updated_at = ?
                   WHERE project_id = ? AND id IN (
                       SELECT coverage_id FROM coverage_intents
                       WHERE project_id = ? AND intent_id = ?
                   )""",
                (fid, now, project_id, project_id, intent_id),
            )
        else:
            reconcile_fact_coverage(
                conn,
                project_id,
                fid,
                intent_id=intent_id,
                explicit_coverage_refs=body.coverage_refs,
            )
        hypothesis_id = intent_row["hypothesis_id"] if "hypothesis_id" in intent_row.keys() else None
        if hypothesis_id:
            result_status = str(fact_status or "").casefold()
            if fact_only:
                hypothesis_status = "concluded"
            elif informational_intent and result_status in {"informational", "completed"}:
                hypothesis_status = "supported"
            elif result_status in {"confirmed", "verified", "vulnerable"}:
                hypothesis_status = "supported"
            elif result_status == "blocked_by_precondition":
                hypothesis_status = "blocked_by_precondition"
            elif result_status in {"not_vulnerable", "refuted", "false_positive"}:
                hypothesis_status = "refuted"
            else:
                hypothesis_status = "inconclusive"
            conn.execute(
                """UPDATE hypotheses SET status = ?, last_error = NULL,
                   coverage_id = COALESCE(coverage_id, ?), intent_id = ?, updated_at = ?
                   WHERE project_id = ? AND id = ?""",
                (
                    hypothesis_status, body.coverage_refs[0] if body.coverage_refs else None,
                    intent_id, now, project_id, hypothesis_id,
                ),
            )
        clear_completion_blocked(conn, project_id)
        if project.mode != "real_website":
            reconcile_project_attack_paths(conn, project_id)

        updated = conn.execute(
            "SELECT * FROM intents WHERE id = ? AND project_id = ?",
            (intent_id, project_id),
        ).fetchone()

        created_fact = conn.execute(
            "SELECT * FROM facts WHERE id = ? AND project_id = ?",
            (fid, project_id),
        ).fetchone()
        assert created_fact is not None
        return ConcludeResponse(
            fact=fact_to_model(conn, created_fact, project_id),
            intent=intent_to_model(conn, updated, project_id),
        )


def _is_verify_action(action_kind: str) -> bool:
    normalized = str(action_kind or "").strip().casefold().replace("-", "_")
    return (
        normalized == "verify"
        or normalized.startswith("verify_")
        or normalized.startswith("verification")
    )


def _stored_json_list(value) -> list:
    if isinstance(value, list):
        return list(value)
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return list(parsed) if isinstance(parsed, list) else []


def _bool_to_db(value: bool | None) -> int | None:
    if value is None:
        return None
    return int(value)

def _resolve_test_variant(
    conn,
    project_id: str,
    mode: str,
    coverage_refs: list[str],
    requested: str | None,
) -> str | None:
    if mode != "real_website":
        return requested
    if len(coverage_refs) > 1:
        raise HTTPException(422, "A real_website Intent may bind at most one Coverage item")
    if not coverage_refs:
        return requested
    row = conn.execute(
        "SELECT test_variants FROM coverage_items WHERE project_id = ? AND id = ?",
        (project_id, coverage_refs[0]),
    ).fetchone()
    try:
        raw_variants = json.loads(row["test_variants"] or "[]")
    except (TypeError, json.JSONDecodeError):
        raw_variants = []
    if not isinstance(raw_variants, list):
        raw_variants = []
    variants = [str(value).strip() for value in raw_variants if str(value).strip()]
    if requested:
        if variants:
            matched = next((value for value in variants if requested.casefold() == value.casefold()), None)
            if matched is None:
                raise HTTPException(422, "Intent test_variant is not declared by the bound Coverage item")
            return matched
        return requested
    if len(variants) == 1:
        return variants[0]
    if len(variants) > 1:
        raise HTTPException(422, "test_variant is required when Coverage declares multiple variants")
    return None
