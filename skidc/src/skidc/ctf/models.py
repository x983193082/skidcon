"""CTF domain contracts, deliberately free of Web assessment fields."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000)]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CreateProject(Contract):
    title: Title
    origin: Text
    goal: Text
    mode: Literal["ctf"] = "ctf"
    bootstrap_enabled: StrictBool = True


class CreateHint(Contract):
    content: Text
    creator: Title = "operator"


class Project(Contract):
    id: str
    title: str
    mode: Literal["ctf"] = "ctf"
    status: Literal["draft", "active", "stopped", "completed"] = "draft"
    origin_fact_id: Literal["origin"] = "origin"
    goal_fact_id: Literal["goal"] = "goal"
    goal_version: Literal[1] = 1
    bootstrap_enabled: bool
    current_run_id: str | None = None
    created_at: str


class Fact(Contract):
    id: str
    description: str
    source_intent_id: str | None = None
    created_run_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    validity: Literal["active", "superseded", "retracted", "quarantined"] = "active"
    supersedes_fact_id: str | None = None
    validity_reason: str | None = None
    created_at: str


class Intent(Contract):
    id: str
    description: str
    from_: list[str] = Field(default_factory=list, alias="from")
    to_fact_id: str | None = None
    status: Literal["open", "concluded", "cancelled"] = "open"
    created_run_id: str | None = None
    created_at: str


class Hint(Contract):
    id: str
    content: str
    creator: str
    created_at: str


class Completion(Contract):
    id: str
    run_id: str
    task_id: str
    from_: list[str] = Field(alias='from')
    to: Literal['goal'] = 'goal'
    description: str
    method: Literal['model_reasoned']
    revision: int
    goal_version: Literal[1]
    created_at: str


class Board(Contract):
    project: Project
    revision: int
    facts: list[Fact]
    intents: list[Intent]
    hints: list[Hint]
    completion: Completion | None = None
