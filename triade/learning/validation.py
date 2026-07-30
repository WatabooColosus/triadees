"""Evidence-based learning lifecycle; observations are never called learning."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, model_validator

LearningState = Literal[
    "observed",
    "hypothesis_created",
    "evaluation_pending",
    "evaluated",
    "application_pending",
    "applied",
    "regression_check_pending",
    "validated",
    "rejected",
    "rolled_back",
]


class LearningValidationReceipt(BaseModel):
    learning_id: str
    status: LearningState
    hypothesis: str | None = None
    producer_id: str | None = None
    baseline_ref: str | None = None
    evaluator_id: str | None = None
    evaluation_set_ref: str | None = None
    before_score: float | None = None
    after_score: float | None = None
    application_ref: str | None = None
    regression_critical: bool = False
    rollback_ref: str | None = None
    rollback_verified: bool = False
    created_at: str
    updated_at: str

    @model_validator(mode="after")
    def validated_requires_all_gates(self) -> LearningValidationReceipt:
        if self.status != "validated":
            return self
        required = (
            self.hypothesis,
            self.producer_id,
            self.baseline_ref,
            self.evaluator_id,
            self.evaluation_set_ref,
            self.application_ref,
            self.rollback_ref,
        )
        if not all(required):
            raise ValueError("validated_learning_missing_gate")
        if self.evaluator_id == self.producer_id:
            raise ValueError("validated_learning_requires_independent_evaluator")
        if self.before_score is None or self.after_score is None:
            raise ValueError("validated_learning_requires_before_after")
        if self.after_score <= self.before_score:
            raise ValueError("validated_learning_requires_improvement")
        if self.regression_critical:
            raise ValueError("validated_learning_cannot_have_critical_regression")
        if not self.rollback_verified:
            raise ValueError("validated_learning_requires_verified_rollback")
        return self


class LearningValidationService:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/017_learning_validation.sql"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def observe(self) -> LearningValidationReceipt:
        return self._new("observed")

    def hypothesize(
        self, hypothesis: str, *, producer_id: str
    ) -> LearningValidationReceipt:
        return self._new(
            "hypothesis_created", hypothesis=hypothesis, producer_id=producer_id
        )

    def assess(
        self,
        receipt: LearningValidationReceipt,
        *,
        rollback: Callable[[], bool] | None = None,
    ) -> LearningValidationReceipt:
        data = receipt.model_dump()
        if (
            not receipt.baseline_ref
            or not receipt.evaluation_set_ref
            or receipt.after_score is None
        ):
            data["status"] = "evaluation_pending"
        elif not receipt.application_ref:
            data["status"] = "evaluated"
        elif receipt.regression_critical or (
            receipt.before_score is not None
            and receipt.after_score <= receipt.before_score
        ):
            rolled_back = bool(rollback and rollback())
            data["status"] = "rolled_back" if rolled_back else "rejected"
            data["rollback_verified"] = rolled_back
        else:
            data["status"] = "validated"
        data["updated_at"] = self._now()
        result = LearningValidationReceipt.model_validate(data)
        self.save(result)
        return result

    def save(self, receipt: LearningValidationReceipt) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO learning_validation_receipts VALUES(?,?,?,?,?)
                ON CONFLICT(learning_id) DO UPDATE SET status=excluded.status,
                payload_json=excluded.payload_json,updated_at=excluded.updated_at""",
                (
                    receipt.learning_id,
                    receipt.status,
                    json.dumps(receipt.model_dump(), ensure_ascii=False),
                    receipt.created_at,
                    receipt.updated_at,
                ),
            )

    def _new(self, status: LearningState, **values: Any) -> LearningValidationReceipt:
        now = self._now()
        receipt = LearningValidationReceipt(
            learning_id=f"learning-{uuid4().hex}",
            status=status,
            created_at=now,
            updated_at=now,
            **values,
        )
        self.save(receipt)
        return receipt
