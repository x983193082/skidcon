"""Short transactional operations on a CTF blackboard; no execution side effects."""
from datetime import datetime, timezone
import json
import sqlite3
from uuid import uuid4

from .db import CtfDatabase
from .models import Board, Completion, CreateHint, CreateProject, Fact, Hint, Intent, Project


class ProjectNotFound(LookupError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entity(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys() if key != "project_id"}


class BoardStore:
    def __init__(self, database: CtfDatabase):
        self.database = database

    def create_project(self, body: CreateProject) -> Board:
        pid, now = str(uuid4()), _now()
        with self.database.connection(write=True) as conn:
            conn.execute(
                "INSERT INTO projects(id,title,bootstrap_enabled,created_at) VALUES(?,?,?,?)",
                (pid, body.title, int(body.bootstrap_enabled), now),
            )
            conn.executemany(
                "INSERT INTO facts(project_id,id,description,created_at) VALUES(?,?,?,?)",
                [(pid, "origin", body.origin, now), (pid, "goal", body.goal, now)],
            )
            conn.execute("INSERT INTO board_state VALUES(?,1)", (pid,))
            return self._board(conn, pid)

    def list_projects(self, limit: int = 100, offset: int = 0) -> list[Project]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Expected limit 1..100 and nonnegative offset")
        with self.database.connection() as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY created_at,id LIMIT ? OFFSET ?", (limit, offset))
            return [Project.model_validate(dict(row)) for row in rows]

    def get_board(self, project_id: str) -> Board:
        with self.database.connection() as conn:
            return self._board(conn, project_id)

    @staticmethod
    def _board(conn: sqlite3.Connection, project_id: str) -> Board:
        project = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if project is None:
            raise ProjectNotFound(project_id)
        revision = conn.execute("SELECT semantic_revision FROM board_state WHERE project_id=?", (project_id,)).fetchone()[0]
        facts = []
        for row in conn.execute("SELECT * FROM facts WHERE project_id=? ORDER BY created_at,id", (project_id,)):
            values = _entity(row)
            values["evidence_refs"] = json.loads(values["evidence_refs"])
            facts.append(Fact.model_validate(values))
        sources: dict[str, list[str]] = {}
        for row in conn.execute("SELECT intent_id,fact_id FROM intent_sources WHERE project_id=? ORDER BY intent_id,fact_id", (project_id,)):
            sources.setdefault(row["intent_id"], []).append(row["fact_id"])
        intents = [Intent.model_validate({**_entity(row), "from": sources.get(row["id"], [])}) for row in conn.execute(
            "SELECT * FROM intents WHERE project_id=? ORDER BY created_at,id", (project_id,),
        )]
        hints = [Hint.model_validate(_entity(row)) for row in conn.execute(
            "SELECT * FROM hints WHERE project_id=? ORDER BY created_at,id", (project_id,),
        )]
        completed = conn.execute('SELECT * FROM completions WHERE project_id=?', (project_id,)).fetchone()
        completion = None
        if completed is not None:
            refs = [r[0] for r in conn.execute('SELECT fact_id FROM completion_sources WHERE project_id=? ORDER BY fact_id', (project_id,))]
            completion = Completion.model_validate({**_entity(completed), 'from': refs})
        return Board(project=Project.model_validate(dict(project)), revision=revision, facts=facts, intents=intents, hints=hints, completion=completion)

    def add_hint(self, project_id: str, body: CreateHint) -> Hint:
        hint = Hint(id=str(uuid4()), content=body.content, creator=body.creator, created_at=_now())
        with self.database.connection(write=True) as conn:
            if conn.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is None:
                raise ProjectNotFound(project_id)
            conn.execute(
                "INSERT INTO hints(project_id,id,content,creator,created_at) VALUES(?,?,?,?,?)",
                (project_id, hint.id, hint.content, hint.creator, hint.created_at),
            )
            conn.execute("UPDATE board_state SET semantic_revision=semantic_revision+1 WHERE project_id=?", (project_id,))
        return hint
