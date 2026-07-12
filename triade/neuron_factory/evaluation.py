"""Evaluación y promoción controlada de candidatos de neurona."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from triade.evaluation import EvaluationComparison, EvaluationRun
from triade.learning.evidence_bridge import LearningEvidenceBridge
from triade.regression import MetricPolicy, RegressionGate

from .candidate import NeuronCandidateFactory
from .store import NeuronSpecificationStore


class NeuronEvaluationCoordinator:
    """Une artefactos de sandbox, Measurement Core y Regression Gate."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.candidates = NeuronCandidateFactory(self.db_path)
        self.specifications = NeuronSpecificationStore(self.db_path)
        self.evidence = LearningEvidenceBridge(self.db_path)
        self.regression = RegressionGate(self.db_path)

    def record_evidence(
        self,
        candidate_id: str,
        *,
        hypothesis: str,
        capability: str,
        baseline: EvaluationRun,
        candidate: EvaluationRun,
        comparison: EvaluationComparison,
        policies: tuple[MetricPolicy, ...],
        artifact_ref: str,
    ) -> dict[str, Any]:
        manifest = self._require_executed(candidate_id)
        if baseline.subject_id != candidate.subject_id:
            raise ValueError("baseline y candidate deben medir el mismo subject_id")
        if not policies:
            raise ValueError("se requiere al menos una política de no-regresión")

        self.evidence.declare_hypothesis(
            candidate_id,
            hypothesis=hypothesis,
            capability=capability,
            subject_id=baseline.subject_id,
            require_regression=True,
        )
        self.evidence.record_comparison(
            candidate_id,
            baseline=baseline,
            candidate=candidate,
            comparison=comparison,
            artifact_ref=artifact_ref,
        )
        report = self.regression.evaluate(
            report_id=f"neuron-regression-{uuid.uuid4().hex}",
            candidate_id=candidate_id,
            capability=capability,
            baseline=baseline,
            candidate=candidate,
            policies=policies,
            metadata={
                "neuron_id": manifest["neuron_id"],
                "version": manifest["version"],
                "artifact_ref": artifact_ref,
            },
        )
        self.evidence.record_regression_report(candidate_id, report)
        return {
            "candidate_id": candidate_id,
            "measurement_decision": comparison.decision,
            "regression_decision": report.decision,
            "report_id": report.report_id,
            "promotable": comparison.decision == "improved" and report.decision == "pass",
        }

    def promote(self, candidate_id: str) -> dict[str, Any]:
        manifest = self._require_executed(candidate_id)
        evidence = self.evidence.require_improvement(candidate_id)
        specification = self.specifications.get(manifest["neuron_id"], manifest["version"])
        if specification is None:
            raise KeyError("la especificación del candidato ya no existe")
        if specification["state"] != "evaluated":
            raise ValueError("la neurona debe estar evaluada antes de promoción")

        promoted = self.specifications.transition(
            manifest["neuron_id"], manifest["version"], "promoted"
        )
        self._set_candidate_status(candidate_id, "promoted")
        return {
            "candidate_id": candidate_id,
            "neuron_id": manifest["neuron_id"],
            "version": manifest["version"],
            "status": "promoted",
            "evidence": evidence,
            "specification": promoted,
        }

    def quarantine(self, candidate_id: str, reason: str) -> dict[str, Any]:
        manifest = self._require_executed(candidate_id)
        if not reason.strip():
            raise ValueError("reason es obligatorio")
        specification = self.specifications.get(manifest["neuron_id"], manifest["version"])
        if specification is None:
            raise KeyError("la especificación del candidato ya no existe")
        if specification["state"] != "evaluated":
            raise ValueError("solo una neurona evaluada puede entrar en cuarentena")
        quarantined = self.specifications.transition(
            manifest["neuron_id"], manifest["version"], "quarantined"
        )
        self._set_candidate_status(candidate_id, "quarantined")
        return {
            "candidate_id": candidate_id,
            "status": "quarantined",
            "reason": reason.strip(),
            "specification": quarantined,
        }

    def _require_executed(self, candidate_id: str) -> dict[str, Any]:
        manifest = self.candidates.get(candidate_id)
        if manifest is None:
            raise KeyError(f"candidato no registrado: {candidate_id}")
        if manifest.get("status") != "executed":
            raise ValueError("el candidato debe estar ejecutado antes de evaluación")
        return manifest

    def _set_candidate_status(self, candidate_id: str, status: str) -> None:
        manifest = self.candidates.get(candidate_id)
        assert manifest is not None
        updated = dict(manifest)
        updated["status"] = status
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE neuron_candidates SET status = ?, manifest_json = ? WHERE candidate_id = ?",
                (status, json.dumps(updated, sort_keys=True), candidate_id),
            )
