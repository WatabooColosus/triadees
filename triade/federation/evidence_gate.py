"""Validación local de evidencia federada y reputación derivada."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.evaluation import EvaluationRun, MetricResult
from triade.regression import MetricPolicy, RegressionGate

from .registry import FederatedNodeRegistry


class FederatedEvidenceGate:
    """Convierte evidencia remota en medición local y aplica confianza conservadora."""

    TRUST_DELTAS = {"pass": 0.03, "warn": -0.02, "fail": -0.15, "invalid": -0.25}

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry = FederatedNodeRegistry(self.db_path)
        self.regression = RegressionGate(self.db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS federated_jobs (
                    job_id TEXT PRIMARY KEY,
                    remote_node_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    result_sha256 TEXT,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_federated_jobs_status
                    ON federated_jobs(status, remote_node_id);
                CREATE TABLE IF NOT EXISTS federated_evidence_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL UNIQUE,
                    node_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    regression_report_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    trust_before REAL NOT NULL,
                    trust_after REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_federated_evidence_node
                    ON federated_evidence_assessments(node_id, decision, created_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def assess(self, job_id: str) -> dict[str, Any]:
        existing = self.get_by_job(job_id)
        if existing is not None:
            return {**existing, "idempotent": True}

        job = self._load_completed_job(job_id)
        node_id = job["remote_node_id"]
        capability = job["capability"]
        result = job["payload"]["result"]
        evidence = result["evidence"]
        expected_sha = result["evidence_sha256"]
        actual_sha = self._sha(evidence)
        if actual_sha != expected_sha:
            raise ValueError("la evidencia persistida no coincide con su huella")

        baseline = self._run(evidence.get("baseline"), "baseline")
        candidate = self._run(evidence.get("candidate"), "candidate")
        policies = self._policies(evidence.get("policies"))
        assessment_id = f"federated-assessment:{job_id}"
        report_id = f"federated-regression:{job_id}"
        report = self.regression.evaluate(
            report_id=report_id,
            candidate_id=job_id,
            capability=capability,
            baseline=baseline,
            candidate=candidate,
            policies=policies,
            metadata={
                "source": "federated",
                "job_id": job_id,
                "node_id": node_id,
                "evidence_sha256": actual_sha,
            },
        )
        trust_before, trust_after, node_state = self._apply_reputation(
            node_id,
            report.decision,
            report_id=report_id,
        )
        payload = {
            "assessment_id": assessment_id,
            "job_id": job_id,
            "node_id": node_id,
            "capability": capability,
            "evidence_sha256": actual_sha,
            "regression_report": report.to_dict(),
            "decision": report.decision,
            "trust_before": trust_before,
            "trust_after": trust_after,
            "node_state": node_state,
        }
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO federated_evidence_assessments
                (assessment_id, job_id, node_id, capability, evidence_sha256,
                 regression_report_id, decision, trust_before, trust_after, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assessment_id,
                    job_id,
                    node_id,
                    capability,
                    actual_sha,
                    report_id,
                    report.decision,
                    trust_before,
                    trust_after,
                    json.dumps(payload, sort_keys=True),
                ),
            )
        return {**payload, "idempotent": False}

    def get_by_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM federated_evidence_assessments WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def _load_completed_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT remote_node_id, capability, status, payload_json
                FROM federated_jobs WHERE job_id = ?""",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"trabajo federado no registrado: {job_id}")
        if row["status"] != "completed":
            raise ValueError("solo se puede evaluar evidencia de trabajos completed")
        return {
            "remote_node_id": row["remote_node_id"],
            "capability": row["capability"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]),
        }

    @staticmethod
    def _run(payload: Any, label: str) -> EvaluationRun:
        if not isinstance(payload, dict):
            raise ValueError(f"evidence.{label} es obligatorio")
        results = payload.get("results")
        if not isinstance(results, list) or not results:
            raise ValueError(f"evidence.{label}.results debe contener métricas")
        return EvaluationRun(
            evaluation_id=str(payload["evaluation_id"]),
            suite_id=str(payload["suite_id"]),
            suite_version=str(payload["suite_version"]),
            subject_id=str(payload["subject_id"]),
            results=tuple(MetricResult(**item) for item in results),
            aggregate_score=float(payload["aggregate_score"]),
            created_at=str(payload["created_at"]),
            metadata={**dict(payload.get("metadata") or {}), "source": "federated"},
        )

    @staticmethod
    def _policies(payload: Any) -> tuple[MetricPolicy, ...]:
        if not isinstance(payload, list) or not payload:
            raise ValueError("evidence.policies debe contener al menos una política")
        return tuple(MetricPolicy(**item) for item in payload)

    def _apply_reputation(self, node_id: str, decision: str, *, report_id: str) -> tuple[float, float, str]:
        node = self.registry.get(node_id)
        if node is None:
            raise KeyError(f"nodo no registrado: {node_id}")
        before = float(node["trust_score"])
        after = min(1.0, max(0.0, before + self.TRUST_DELTAS[decision]))
        state = str(node["state"])
        if decision in {"fail", "invalid"} or after < 0.5:
            if state == "trusted":
                node = self.registry.transition(
                    node_id,
                    "quarantined",
                    actor="federated-evidence-gate",
                    reason=f"evidencia remota bloqueada por {report_id}: {decision}",
                    trust_score=after,
                )
                return before, after, str(node["state"])
        self._update_trust(node_id, after, decision=decision, report_id=report_id)
        return before, after, state

    def _update_trust(self, node_id: str, score: float, *, decision: str, report_id: str) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM federated_nodes_v2 WHERE node_id = ?",
                (node_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"nodo no registrado: {node_id}")
            payload = json.loads(row["payload_json"])
            payload["trust_score"] = score
            conn.execute(
                """UPDATE federated_nodes_v2 SET trust_score = ?, payload_json = ?,
                updated_at = CURRENT_TIMESTAMP WHERE node_id = ?""",
                (score, json.dumps(payload, sort_keys=True), node_id),
            )
            conn.execute(
                """INSERT INTO federated_node_events
                (node_id, action, actor, reason, payload_json)
                VALUES (?, ?, 'federated-evidence-gate', ?, ?)""",
                (
                    node_id,
                    "trust:adjusted",
                    f"regression report {report_id}: {decision}",
                    json.dumps(payload, sort_keys=True),
                ),
            )

    @staticmethod
    def _sha(payload: dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
