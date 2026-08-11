"""Ciclo autónomo gobernado con baseline, transfer, rollback y receipt."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.db import sqlite3

SCHEMA = Path(__file__).resolve().parent.parent / "memory/schemas.sql"
MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "memory/migrations/025_autonomous_learning_cycle.sql"
)
KNOWN_COMMANDS = {"status", "identity verify", "runtime doctor"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CommandInterpreter:
    """Consumidor real de artifacts activos; sin respuestas por caso de test."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def interpret(self, text: str) -> str | None:
        candidate = text.strip().lower()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT operation, configuration_json
                FROM autonomous_learning_artifacts
                WHERE status IN ('active', 'consolidated') ORDER BY created_at"""
            ).fetchall()
        for operation, raw_config in rows:
            config = json.loads(raw_config)
            if operation == "unicode_nfkc_whitespace":
                candidate = unicodedata.normalize("NFKC", candidate)
                if config.get("collapse_whitespace", True):
                    candidate = re.sub(r"\s+", " ", candidate).strip()
        return candidate if candidate in KNOWN_COMMANDS else None


class NormalizationArtifactGenerator:
    """Generador acotado: convierte evidencia de gap en un change set declarativo."""

    def generate(self, *, gap_ref: str, research_ref: str) -> dict[str, Any]:
        if not gap_ref.strip() or not research_ref.strip():
            raise ValueError("gap_ref y research_ref son obligatorios")
        return {
            "capability": "command_normalization",
            "operation": "unicode_nfkc_whitespace",
            "configuration": {"collapse_whitespace": True},
            "gap_ref": gap_ref,
            "research_ref": research_ref,
        }


class IndependentCommandEvaluator:
    """Evaluador separado del generador y basado solo en input/expected."""

    @staticmethod
    def evaluate(
        interpreter: CommandInterpreter,
        cases: Sequence[tuple[str, str | None]],
    ) -> dict[str, Any]:
        observations = [
            {
                "input": text,
                "expected": expected,
                "observed": interpreter.interpret(text),
            }
            for text, expected in cases
        ]
        successes = sum(item["expected"] == item["observed"] for item in observations)
        return {
            "score": successes / max(len(observations), 1),
            "successes": successes,
            "total": len(observations),
            "observations": observations,
        }


class GovernedAutonomousLearningCycle:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA.read_text(encoding="utf-8"))
            conn.executescript(MIGRATION.read_text(encoding="utf-8"))

    def run(
        self, *, gap_ref: str, research_ref: str, evidence_dir: str | Path
    ) -> dict[str, Any]:
        evidence_root = Path(evidence_dir)
        evidence_root.mkdir(parents=True, exist_ok=True)
        interpreter = CommandInterpreter(self.db_path)
        evaluator = IndependentCommandEvaluator()
        creation_cases = [("ｓｔａｔｕｓ", "status")]
        transfer_cases = [("ｉｄｅｎｔｉｔｙ　ｖｅｒｉｆｙ", "identity verify")]
        regression_cases = [
            ("status", "status"),
            ("identity verify", "identity verify"),
            ("unknown command", None),
        ]
        baseline = evaluator.evaluate(interpreter, creation_cases)
        generated = NormalizationArtifactGenerator().generate(
            gap_ref=gap_ref, research_ref=research_ref
        )
        artifact_id = f"la-{uuid.uuid4().hex}"
        rollback_ref = f"rollback:{artifact_id}:disable"
        now = _now()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO autonomous_learning_artifacts VALUES
                (?, ?, ?, ?, 'candidate', ?, ?, ?, ?)""",
                (
                    artifact_id,
                    generated["capability"],
                    generated["operation"],
                    json.dumps(generated["configuration"]),
                    research_ref,
                    rollback_ref,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE autonomous_learning_artifacts SET status='canary', updated_at=? WHERE artifact_id=?",
                (_now(), artifact_id),
            )
            conn.execute(
                "UPDATE autonomous_learning_artifacts SET status='active', updated_at=? WHERE artifact_id=?",
                (_now(), artifact_id),
            )
        repetitions = [
            evaluator.evaluate(interpreter, creation_cases) for _ in range(5)
        ]
        post = repetitions[-1]
        transfer = evaluator.evaluate(interpreter, transfer_cases)
        regression = evaluator.evaluate(interpreter, regression_cases)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE autonomous_learning_artifacts SET status='rolled_back', updated_at=? WHERE artifact_id=?",
                (_now(), artifact_id),
            )
        rollback_measurement = evaluator.evaluate(interpreter, creation_cases)
        rollback = {
            "rollback_ref": rollback_ref,
            "status": "verified" if rollback_measurement == baseline else "failed",
            "measurement": rollback_measurement,
        }
        improvement = post["score"] - baseline["score"]
        promotable = (
            improvement > 0
            and all(item["score"] == post["score"] for item in repetitions)
            and transfer["score"] > baseline["score"]
            and regression["score"] == 1.0
            and rollback["status"] == "verified"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE autonomous_learning_artifacts SET status=?, updated_at=?
                WHERE artifact_id=?""",
                ("consolidated" if promotable else "rejected", _now(), artifact_id),
            )
        restarted = CommandInterpreter(self.db_path)
        restart = evaluator.evaluate(restarted, creation_cases + transfer_cases)
        restart_verified = promotable and restart["score"] == 1.0
        receipt_id = f"lr-{uuid.uuid4().hex}"
        evidence_bundle = evidence_root / f"{receipt_id}.json"
        receipt = {
            "learning_receipt_id": receipt_id,
            "artifact_id": artifact_id,
            "gap_ref": gap_ref,
            "research_ref": research_ref,
            "baseline": baseline,
            "post_measurement": post,
            "repetitions": repetitions,
            "improvement": improvement,
            "transfer": transfer,
            "regression": regression,
            "rollback": rollback,
            "restart": {**restart, "verified": restart_verified},
            "decision": "consolidated"
            if promotable and restart_verified
            else "rejected",
            "generator": "NormalizationArtifactGenerator",
            "evaluator": "IndependentCommandEvaluator",
            "benchmark_separation": {
                "creation_inputs": [case[0] for case in creation_cases],
                "transfer_inputs": [case[0] for case in transfer_cases],
            },
        }
        evidence_bundle.write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO autonomous_learning_receipts VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    receipt_id,
                    artifact_id,
                    gap_ref,
                    research_ref,
                    json.dumps(baseline),
                    json.dumps(post),
                    json.dumps(transfer),
                    json.dumps(regression),
                    json.dumps(rollback),
                    json.dumps(receipt["restart"]),
                    receipt["decision"],
                    json.dumps({"path": str(evidence_bundle)}),
                    _now(),
                ),
            )
        return {**receipt, "evidence_bundle": str(evidence_bundle)}
