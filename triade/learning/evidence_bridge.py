"""Puente entre LearningPipeline, Measurement Core y Regression Gate."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.capabilities import CapabilityPolicyGuard, CapabilityRegistry
from triade.core.contracts import utc_now
from triade.evaluation import EvaluationComparison, EvaluationRun
from triade.regression import RegressionGate, RegressionReport


class LearningEvidenceBridge:
    """Persiste hipótesis y evidencia antes/después por candidato."""

    PROMOTABLE_DECISIONS = frozenset({"improved"})

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self.regression_gate = RegressionGate(db_path=self.db_path)
        self.capability_registry = CapabilityRegistry(self.db_path)
        self.capability_policy = CapabilityPolicyGuard(self.db_path)

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
                    regression_required INTEGER NOT NULL DEFAULT 0,
                    regression_report_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(learning_evidence)").fetchall()
            }
            if "regression_required" not in columns:
                conn.execute(
                    "ALTER TABLE learning_evidence ADD COLUMN regression_required INTEGER NOT NULL DEFAULT 0"
                )
            if "regression_report_id" not in columns:
                conn.execute(
                    "ALTER TABLE learning_evidence ADD COLUMN regression_report_id TEXT"
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
        require_regression: bool = False,
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
                (candidate_id, hypothesis, capability, subject_id, decision,
                 regression_required, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    hypothesis=excluded.hypothesis,
                    capability=excluded.capability,
                    subject_id=excluded.subject_id,
                    regression_required=excluded.regression_required,
                    updated_at=excluded.updated_at""",
                (
                    candidate_id,
                    clean_hypothesis,
                    clean_capability,
                    clean_subject,
                    1 if require_regression else 0,
                    now,
                    now,
                ),
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

    def record_regression_report(
        self,
        candidate_id: str,
        report: RegressionReport,
    ) -> dict[str, Any]:
        evidence = self.get(candidate_id)
        if evidence is None:
            raise ValueError("Primero debe declararse una hipótesis de mejora")
        if report.candidate_id != candidate_id:
            raise ValueError("El reporte de regresión no corresponde al candidato")
        if report.capability != evidence["capability"]:
            raise ValueError("El reporte de regresión no corresponde a la capacidad declarada")
        with self._connect() as conn:
            conn.execute(
                """UPDATE learning_evidence SET
                    regression_required=1,
                    regression_report_id=?,
                    updated_at=?
                WHERE candidate_id=?""",
                (report.report_id, utc_now(), candidate_id),
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
        if evidence.get("regression_required"):
            report_id = evidence.get("regression_report_id")
            if not report_id:
                raise ValueError("Regression Gate requerido pero no existe reporte asociado")
            report = self.regression_gate.require_pass(candidate_id)
            if report.report_id != report_id:
                raise ValueError("El reporte vigente de Regression Gate no coincide con la evidencia")
            evidence["regression_report"] = report.to_dict()

        capability_id = str(evidence.get("capability") or "").strip()
        registered = self.capability_registry.get(capability_id)
        if registered is not None:
            capability = self.capability_policy.require(capability_id, "promote")
            evidence["capability_policy"] = {
                "allowed": True,
                "capability_id": capability_id,
                "version": capability.get("version"),
                "state": capability.get("state"),
            }
        return evidence

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM learning_evidence WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["regression_required"] = bool(result.get("regression_required"))
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
        latest = self.regression_gate.latest_for_candidate(candidate_id)
        result["regression_report"] = latest.to_dict() if latest else None
        result["regression_quarantined"] = self.regression_gate.is_quarantined(candidate_id)
        return result
