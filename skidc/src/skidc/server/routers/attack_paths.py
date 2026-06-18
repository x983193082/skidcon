from __future__ import annotations

import json

from fastapi import APIRouter

from skidc.server.db import get_conn
from skidc.server.models import AttackPath, CreateAttackPathRequest
from skidc.server.services import (
    check_project_active,
    get_project_or_404,
    next_attack_path_id,
    utcnow,
    validate_facts_exist,
)

router = APIRouter(tags=["attack_paths"])


def _row_to_model(row) -> AttackPath:
    return AttackPath(
        id=row["id"],
        name=row["name"],
        fact_chain=json.loads(row["fact_chain"]),
        description=row["description"],
        severity=row["severity"],
        created_at=row["created_at"],
    )


@router.get("/projects/{project_id}/attack-paths", response_model=list[AttackPath])
def list_attack_paths(project_id: str):
    with get_conn() as conn:
        get_project_or_404(conn, project_id)
        rows = conn.execute(
            "SELECT * FROM attack_paths WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [_row_to_model(r) for r in rows]


@router.post(
    "/projects/{project_id}/attack-paths",
    response_model=AttackPath,
    status_code=201,
)
def create_attack_path(project_id: str, body: CreateAttackPathRequest):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        validate_facts_exist(conn, project_id, body.fact_chain)
        now = utcnow()
        aid = next_attack_path_id(conn, project_id)
        conn.execute(
            "INSERT INTO attack_paths (id, project_id, name, fact_chain, description, severity, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (aid, project_id, body.name, json.dumps(body.fact_chain), body.description, body.severity, now),
        )
        return AttackPath(
            id=aid,
            name=body.name,
            fact_chain=body.fact_chain,
            description=body.description,
            severity=body.severity,
            created_at=now,
        )


@router.delete("/projects/{project_id}/attack-paths/{path_id}", status_code=204)
def delete_attack_path(project_id: str, path_id: str):
    with get_conn() as conn:
        check_project_active(conn, project_id)
        conn.execute(
            "DELETE FROM attack_paths WHERE id = ? AND project_id = ?",
            (path_id, project_id),
        )
