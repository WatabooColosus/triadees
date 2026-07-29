"""Predicción y calibración verificable de capacidades."""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

SCHEMA = Path(__file__).resolve().parent.parent / "memory/schemas.sql"
MIGRATION = (
    Path(__file__).resolve().parent.parent / "memory/migrations/023_metacognition.sql"
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CapabilityAwareness:
    STATES: ClassVar[set[str]] = {
        "available",
        "degraded",
        "unavailable",
        "unverified",
        "quarantined",
    }
    ERROR_TYPES: ClassVar[set[str]] = {
        "dependency_unavailable",
        "resource_exhausted",
        "permission_denied",
        "timeout",
        "invalid_input",
        "postcondition_failed",
        "unknown",
    }

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def register(
        self,
        capability_id: str,
        availability: str,
        *,
        dependencies: list[str] | None = None,
        resources: dict[str, Any] | None = None,
        utility: float = 0.5,
        risk: float = 0.5,
        reason: str,
    ) -> dict[str, Any]:
        if availability not in self.STATES:
            raise ValueError(f"availability inválida: {availability}")
        if not capability_id.strip() or not reason.strip():
            raise ValueError("capability_id y reason son obligatorios")
        if not 0 <= utility <= 1 or not 0 <= risk <= 1:
            raise ValueError("utility y risk deben estar en [0,1]")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO capability_awareness
                (capability_id, availability, dependencies_json, resources_json,
                 utility, risk, reason, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                  availability=excluded.availability,
                  dependencies_json=excluded.dependencies_json,
                  resources_json=excluded.resources_json,
                  utility=excluded.utility, risk=excluded.risk,
                  reason=excluded.reason, updated_at=excluded.updated_at""",
                (
                    capability_id,
                    availability,
                    json.dumps(dependencies or []),
                    json.dumps(resources or {}),
                    utility,
                    risk,
                    reason,
                    _now(),
                ),
            )
        return self.get(capability_id)

    def get(self, capability_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM capability_awareness WHERE capability_id = ?",
                (capability_id,),
            ).fetchone()
        if row is None:
            raise KeyError(capability_id)
        result = dict(row)
        result["dependencies"] = json.loads(result.pop("dependencies_json"))
        result["resources"] = json.loads(result.pop("resources_json"))
        return result

    def predict(
        self,
        capability_id: str,
        task_ref: str,
        confidence: float,
        *,
        reasons: list[str],
        resources: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        profile = self.get(capability_id)
        if not task_ref.strip() or not reasons:
            raise ValueError("task_ref y reasons son obligatorios")
        requested = max(0.0, min(1.0, confidence))
        ceilings = {
            "available": 1.0,
            "degraded": 0.70,
            "unavailable": 0.05,
            "unverified": 0.30,
            "quarantined": 0.0,
        }
        probability = min(requested, ceilings[str(profile["availability"])])
        prediction_id = f"cp-{uuid.uuid4().hex}"
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO capability_predictions
                (prediction_id, capability_id, task_ref, predicted_success,
                 reasons_json, resources_json, predicted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    prediction_id,
                    capability_id,
                    task_ref,
                    probability,
                    json.dumps(reasons),
                    json.dumps(resources or profile["resources"]),
                    _now(),
                ),
            )
        return {
            "prediction_id": prediction_id,
            "capability_id": capability_id,
            "task_ref": task_ref,
            "confidence": probability,
            "requested_confidence": requested,
            "availability": profile["availability"],
            "reasons": reasons,
            "resources": resources or profile["resources"],
        }

    def record_outcome(
        self,
        prediction_id: str,
        success: bool,
        *,
        evidence_ref: str,
        error_type: str | None = None,
    ) -> dict[str, Any]:
        if not evidence_ref.strip():
            raise ValueError("evidence_ref es obligatorio")
        if not success and error_type not in self.ERROR_TYPES:
            raise ValueError("Un fallo requiere error_type canónico")
        if success and error_type is not None:
            raise ValueError("Un éxito no puede registrar error_type")
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE capability_predictions SET outcome_success = ?,
                error_type = ?, evidence_ref = ?, completed_at = ?
                WHERE prediction_id = ? AND outcome_success IS NULL""",
                (int(success), error_type, evidence_ref, _now(), prediction_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Predicción inexistente o ya cerrada")
        return {
            "prediction_id": prediction_id,
            "success": success,
            "error_type": error_type,
        }

    def calibration(self, bins: int = 10) -> dict[str, Any]:
        if bins <= 0:
            raise ValueError("bins debe ser positivo")
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT predicted_success, outcome_success
                FROM capability_predictions WHERE outcome_success IS NOT NULL"""
            ).fetchall()
        pairs = [(float(row[0]), int(row[1])) for row in rows]
        if not pairs:
            return {"status": "unverified", "sample_size": 0}
        brier = sum(
            math.pow(probability - outcome, 2) for probability, outcome in pairs
        ) / len(pairs)
        bucketed: list[list[tuple[float, int]]] = [[] for _ in range(bins)]
        for pair in pairs:
            bucketed[min(int(pair[0] * bins), bins - 1)].append(pair)
        ece = 0.0
        for bucket in bucketed:
            if bucket:
                mean_probability = sum(pair[0] for pair in bucket) / len(bucket)
                mean_outcome = sum(pair[1] for pair in bucket) / len(bucket)
                ece += len(bucket) / len(pairs) * abs(mean_probability - mean_outcome)
        accuracy = sum(
            (probability >= 0.5) == bool(outcome) for probability, outcome in pairs
        ) / len(pairs)
        high_confidence = [
            (probability, outcome)
            for probability, outcome in pairs
            if probability >= 0.9
        ]
        false_confidence = sum(not outcome for _, outcome in high_confidence) / max(
            len(high_confidence), 1
        )
        unknown = [
            (probability, outcome)
            for probability, outcome in pairs
            if probability <= 0.3
        ]
        unknown_detection = sum(not outcome for _, outcome in unknown) / max(
            len(unknown), 1
        )
        return {
            "status": "measured",
            "sample_size": len(pairs),
            "brier_score": brier,
            "expected_calibration_error": ece,
            "success_prediction_accuracy": accuracy,
            "false_confidence_rate": false_confidence,
            "unknown_detection_rate": unknown_detection,
        }

    def gaps(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM capability_awareness
                WHERE availability IN ('degraded', 'unavailable', 'unverified', 'quarantined')"""
            ).fetchall()
        gaps = []
        for row in rows:
            item = dict(row)
            score = float(item["utility"]) * (1.0 - float(item["risk"]))
            gaps.append(
                {
                    "capability_id": item["capability_id"],
                    "availability": item["availability"],
                    "reason": item["reason"],
                    "learning_priority": score,
                }
            )
        return sorted(
            gaps, key=lambda item: (-item["learning_priority"], item["capability_id"])
        )
