"""Puente entre LearningPipeline y Measurement Core."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.evaluation import EvaluationComparison, EvaluationRun


class LearningEvidenceBridge:
    """Persiste hipótesis y evidencia antes/después por candidato."""

    PROMOTABLE_DECISIONS = frozenset({"improved"})

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS learning_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL UNIQUE,
                    hypothesis TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    baseline_evaluation_json TEXT,
                    candidate_evaluation_json TEXT,
                    comparison_json TEXT,
                    decision TEXT DEFAULT 'pending',
                    critical_regressions_json TEXT DEFAULT '[]',
                    artifact_ref TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_evidence_decision ON learning_evidence(decision)"
            )

    def declare_hypothesis(
        self,
        candidate_id: str,
        *,
        hypothesis: str,
        capability: str,
        subject_id: str,
    ) -> dict[str, Any]:
        clean_hypothesis = hypothesis.strip()
        clean_capability = capability.strip()
        clean_subject = subject_id.strip()
        if not all((candidate_id.strip(), clean_hypothesis, clean_capability, clean_subject)):
            raise ValueError("candidate_id, hypothesis, capability y subject_id son obligatorios")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO learning_evidence
                (candidate_id, hypothesis, capability, subject_id, decision, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    hypothesis=excluded.hypothesis,
                    capability=excluded.capability,
                    subject_id=excluded.subject_id,
                    updated_at=excluded.updated_at""",
                (candidate_id, clean_hypothesis, clean_capability, clean_subject, now, now),
            )
        return self.get(candidate_id) or {}

    def record_comparison(
        self,
        candidate_id: str,
        *,
        baseline: EvaluationRun,
        candidate: EvaluationRun,
        comparison: EvaluationComparison,
        artifact_ref: str | None = None,
    ) -> dict[str, Any]:
        evidence = self.get(candidate_id)
        if evidence is None:
            raise ValueError("Primero debe declararse una hipótesis de mejora")
        expected_subject = str(evidence["subject_id"])
        if baseline.subject_id != expected_subject or candidate.subject_id != expected_subject:
            raise ValueError("La evidencia no corresponde al subject_id declarado")
        if comparison.baseline_evaluation_id != baseline.evaluation_id:
            raise ValueError("baseline_evaluation_id inconsistente")
        if comparison.candidate_evaluation_id != candidate.evaluation_id:
            raise ValueError("candidate_evaluation_id inconsistente")
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """UPDATE learning_evidence SET
                    baseline_evaluation_json=?, candidate_evaluation_json=?, comparison_json=?,
                    decision=?, critical_regressions_json=?, artifact_ref=?, updated_at=?
                WHERE candidate_id=?""",
                (
                    json.dumps(baseline.to_dict(), ensure_ascii=False),
                    json.dumps(candidate.to_dict(), ensure_ascii=False),
                    json.dumps(comparison.to_dict(), ensure_ascii=False),
                    comparison.decision,
                    json.dumps(list(comparison.critical_regressions), ensure_ascii=False),
                    artifact_ref,
                    now,
                    candidate_id,
                ),
            )
        return self.get(candidate_id) or {}

    def require_improvement(self, candidate_id: str) -> dict[str, Any]:
        evidence = self.get(candidate_id)
        if evidence is None:
            raise ValueError("No existe evidencia Measurement Core para el candidato")
        decision = str(evidence.get("decision") or "pending")
        if decision not in self.PROMOTABLE_DECISIONS:
            raise ValueError(f"La evidencia no demuestra mejora: decision={decision}")
        critical = evidence.get("critical_regressions") or []
        if critical:
            raise ValueError(f"La evidencia contiene regresiones críticas: {critical}")
        if not evidence.get("baseline_evaluation") or not evidence.get("candidate_evaluation"):
            raise ValueError("La evidencia antes/después está incompleta")
        return evidence

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM learning_evidence WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for source, target, default in (
            ("baseline_evaluation_json", "baseline_evaluation", None),
            ("candidate_evaluation_json", "candidate_evaluation", None),
            ("comparison_json", "comparison", None),
            ("critical_regressions_json", "critical_regressions", []),
        ):
            raw = result.pop(source, None)
            try:
                result[target] = json.loads(raw) if raw else default
            except (json.JSONDecodeError, TypeError):
                result[target] = default
        return result
