"""Ledger canónico que separa actividad, efecto, utilidad y aprendizaje."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from triade.db import sqlite3

SCHEMA = Path(__file__).resolve().parent.parent / "memory/schemas.sql"
MIGRATION = (
    Path(__file__).resolve().parent.parent / "memory/migrations/026_utility_ledger.sql"
)

Classification = Literal["activity", "output", "effect", "utility", "learning"]
NON_UTILITY_KINDS = {"heartbeat", "pulse", "pulse_check", "maintenance"}


class UtilityReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(default_factory=lambda: f"ur-{uuid.uuid4().hex}")
    goal: str = Field(min_length=1)
    classification: Classification
    baseline: dict[str, Any]
    outcome: dict[str, Any]
    improvement: float
    quality_score: float = Field(ge=0.0, le=1.0)
    human_intervention: float = Field(ge=0.0)
    time_cost: float = Field(ge=0.0)
    cpu_cost: float = Field(ge=0.0)
    gpu_cost: float = Field(ge=0.0)
    memory_cost: float = Field(ge=0.0)
    storage_cost: float = Field(ge=0.0)
    network_cost: float = Field(ge=0.0)
    risk: str = Field(min_length=1)
    regressions: list[str]
    verified: bool
    evidence_ref: str | None = None
    effect_receipt_ref: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @model_validator(mode="after")
    def verify_semantics(self) -> UtilityReceipt:
        kind = str(self.outcome.get("kind", "")).lower()
        if kind in NON_UTILITY_KINDS and (
            self.classification in {"utility", "learning"} or self.improvement != 0
        ):
            raise ValueError("telemetry_or_maintenance_cannot_claim_utility")
        if (
            self.classification in {"activity", "output", "effect"}
            and self.improvement != 0
        ):
            raise ValueError("improvement_requires_utility_or_learning")
        if self.classification in {"utility", "learning"}:
            if not self.verified or not self.evidence_ref:
                raise ValueError("utility_requires_verified_evidence")
            if not self.effect_receipt_ref:
                raise ValueError("utility_requires_effect_receipt")
            if self.improvement <= 0:
                raise ValueError("utility_requires_positive_improvement")
            if self.regressions:
                raise ValueError("utility_forbidden_with_regressions")
        return self


class UtilityLedger:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    def record(self, receipt: UtilityReceipt) -> UtilityReceipt:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO utility_receipts VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    receipt.receipt_id,
                    receipt.goal,
                    receipt.classification,
                    json.dumps(receipt.baseline, sort_keys=True),
                    json.dumps(receipt.outcome, sort_keys=True),
                    receipt.improvement,
                    receipt.quality_score,
                    receipt.human_intervention,
                    receipt.time_cost,
                    receipt.cpu_cost,
                    receipt.gpu_cost,
                    receipt.memory_cost,
                    receipt.storage_cost,
                    receipt.network_cost,
                    receipt.risk,
                    json.dumps(receipt.regressions),
                    int(receipt.verified),
                    receipt.evidence_ref,
                    receipt.effect_receipt_ref,
                    receipt.created_at,
                ),
            )
        return receipt

    def summary(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT classification, COUNT(*), SUM(improvement)
                FROM utility_receipts GROUP BY classification ORDER BY classification"""
            ).fetchall()
        return {
            "counts": {row[0]: row[1] for row in rows},
            "verified_improvement": sum(float(row[2] or 0.0) for row in rows),
        }
