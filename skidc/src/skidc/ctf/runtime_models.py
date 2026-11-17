"""Dispatcher-injected execution identity is separate from model-generated text."""
from typing import Literal

from pydantic import Field, StrictBool, model_validator

from .models import Contract, Text, Title


class SchedulerPolicy(Contract):
    max_parallel: int = Field(default=2, ge=1, le=8, strict=True)
    batch_size: int = Field(default=4, ge=1, le=16, strict=True)
    max_tasks: int = Field(default=64, ge=1, le=1000, strict=True)
    run_seconds: int = Field(default=900, ge=1, le=86400, strict=True)
    batch_seconds: int = Field(default=120, ge=1, le=3600, strict=True)
    no_progress_limit: int = Field(default=3, ge=1, le=10, strict=True)
    conflict_limit: int = Field(default=3, ge=1, le=10, strict=True)
    wake_seconds: int = Field(default=10, ge=1, le=3600, strict=True)


class StartRun(Contract):
    idempotency_key: Title
    target_instance_id: Title
    scheduler: SchedulerPolicy | None = None


class ClaimNext(Contract):
    worker_instance_id: Title


class ClaimTask(Contract):
    kind: Literal["bootstrap", "reason", "explore"]
    worker_instance_id: Title
    intent_id: Title | None = None

    @model_validator(mode="after")
    def validate_target(self):
        if (self.kind == "explore") != (self.intent_id is not None):
            raise ValueError("Only Explore requires an intent_id")
        return self


class LeaseIdentity(Contract):
    worker_instance_id: Title
    lease_token: Title


class IntentProposal(Contract):
    from_: list[Title] = Field(alias="from", min_length=1, max_length=64)
    description: Text


class BootstrapComplete(Contract):
    fact_description: Text
    complete_description: Text


class TaskResult(LeaseIdentity):
    idempotency_key: Title
    intents: list[IntentProposal] | None = Field(default=None, min_length=1, max_length=16)
    description: Text | None = None
    error: Text | None = None
    no_op: StrictBool | None = None
    complete: IntentProposal | None = None
    bootstrap_complete: BootstrapComplete | None = None

    @model_validator(mode="after")
    def one_result(self):
        if self.no_op is False:
            raise ValueError("no_op must be true when provided")
        if sum(value is not None for value in (self.intents, self.description, self.error, self.no_op, self.complete, self.bootstrap_complete)) != 1:
            raise ValueError("Provide exactly one result branch")
        return self
