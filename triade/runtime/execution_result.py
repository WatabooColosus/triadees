"""Canonical, truthful result contract for governed autonomous execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from triade.runtime.effect_receipt import EffectReceipt

ExecutionStatus = Literal[
    "completed",
    "blocked",
    "skipped",
    "dry_run",
    "observed",
    "cancelled",
    "failed",
    "dead_letter",
    "timeout",
    "lease_lost",
    "deferred",
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class ExecutionResult(BaseModel):
    status: ExecutionStatus
    executed: bool
    effect_applied: bool = False
    retryable: bool = False
    error_code: str | None = None
    message: str = ""
    artifacts: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    resource_usage: dict[str, Any] = Field(default_factory=dict)
    postconditions: dict[str, Any] = Field(default_factory=dict)
    rollback: dict[str, Any] = Field(default_factory=dict)
    effect_receipt: EffectReceipt | None = None
    observation_justification: str | None = None
    started_at: str = Field(default_factory=utc_now)
    finished_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def enforce_truth(self) -> ExecutionResult:
        non_executed = {"blocked", "skipped", "dry_run", "observed", "deferred"}
        failures = {"failed", "dead_letter", "timeout", "lease_lost"}
        if self.status == "completed":
            if not self.executed:
                raise ValueError("completed_requires_executed_true")
            if not self.evidence and not self.observation_justification:
                raise ValueError(
                    "completed_requires_evidence_or_observation_justification"
                )
            if self.postconditions.get("effect_expected") and not self.effect_applied:
                raise ValueError("completed_effect_requires_effect_applied_true")
            if self.effect_receipt is None or not self.effect_receipt.verified:
                raise ValueError("completed_requires_verified_effect_receipt")
            if self.postconditions.get("artifact_required") and not self.artifacts:
                raise ValueError("completed_requires_artifact")
        if self.status in non_executed and self.executed:
            raise ValueError(f"{self.status}_requires_executed_false")
        if self.status in failures and self.postconditions.get("passed") is True:
            raise ValueError("failed_result_cannot_claim_passing_postcondition")
        if self.status == "dry_run" and self.effect_applied:
            raise ValueError("dry_run_cannot_apply_effect")
        return self
