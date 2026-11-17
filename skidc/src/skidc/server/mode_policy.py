"""Server-side workflow boundaries, based on stored immutable project mode."""
from fastapi import HTTPException
from pydantic import BaseModel

from skidc.server.db import get_conn


def project_is_web(conn, project_id: str) -> bool:
    row = conn.execute("SELECT mode FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row is not None and row["mode"] == "real_website"


def require_web_mode(mode: str) -> None:
    if mode != "real_website":
        raise HTTPException(409, detail={
            "code": "engine_mismatch",
            "message": "This operation belongs to the real_website workflow.",
        })


def require_web_project(project_id: str) -> None:
    # Mode cannot change between this read and the handler's transaction.
    with get_conn() as conn:
        row = conn.execute("SELECT mode FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Project not found")
        require_web_mode(row["mode"])


def validate_ctf_write(mode: str, body: BaseModel, allowed: set[str]) -> None:
    if mode != "ctf":
        return
    extra = body.model_fields_set - allowed
    if extra:
        raise HTTPException(422, detail={
            "code": "ctf_contract_violation",
            "fields": sorted(extra),
            "message": "These fields are not part of the CTF blackboard contract.",
        })
