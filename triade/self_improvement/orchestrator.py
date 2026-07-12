"""Orquestación acotada del ciclo completo de auto-mejora."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from triade.evaluation import EvaluationRun, compare_evaluations
from triade.neuron_factory import NeuronEvaluationCoordinator, SandboxExecutionEngine
from triade.regression import MetricPolicy

from .bridge import ImprovementNeuronFactoryBridge
from .canary import CanaryMonitor

EvaluationProvider = Callable[
    [str, dict[str, Any]],
    tuple[EvaluationRun, EvaluationRun, tuple[MetricPolicy, ...]],
]


class SelfImprovementOrchestrator:
    """Ejecuta una sola iteración, sin recursión y con gates obligatorios."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.bridge = ImprovementNeuronFactoryBridge(self.db_path)
        self.execution = SandboxExecutionEngine(self.db_path)
        self.evaluation = NeuronEvaluationCoordinator(self.db_path)
        self.canary = CanaryMonitor(self.db_path)

    def run_once(
        self,
        proposal_id: str,
        *,
        neuron_id: str,
        version: str,
        configuration: dict[str, Any],
        evaluation_provider: EvaluationProvider,
        canary_traffic_percent: int = 10,
        canary_tolerance: float = 0.02,
        canary_min_observations: int = 3,
        canary_max_observations: int = 10,
    ) -> dict[str, Any]:
        linked = self.bridge.create_candidate(
            proposal_id,
            neuron_id=neuron_id,
            version=version,
        )
        candidate_id = linked["candidate"]["candidate_id"]
        try:
            artifact = self.execution.execute_configuration(candidate_id, configuration)
            baseline, candidate, policies = evaluation_provider(candidate_id, artifact)
            comparison = compare_evaluations(baseline, candidate)
            evidence = self.evaluation.record_evidence(
                candidate_id,
                hypothesis=self._proposal(proposal_id)["hypothesis"],
                capability=self._proposal(proposal_id)["requested_capability"],
                baseline=baseline,
                candidate=candidate,
                comparison=comparison,
                policies=policies,
                artifact_ref=artifact["execution_id"],
            )
            if not evidence["promotable"]:
                self.evaluation.quarantine(candidate_id, "evidencia insuficiente o regresión")
                self.bridge.release_candidate(candidate_id, outcome="rejected")
                return self._result(
                    proposal_id,
                    candidate_id,
                    "quarantined",
                    artifact=artifact,
                    evidence=evidence,
                )

            promotion = self.evaluation.promote(candidate_id)
            canary = self.canary.start(
                candidate_id,
                baseline_score=candidate.aggregate_score,
                tolerance=canary_tolerance,
                traffic_percent=canary_traffic_percent,
                min_observations=canary_min_observations,
                max_observations=canary_max_observations,
            )
            self.bridge.release_candidate(candidate_id, outcome="completed")
            return self._result(
                proposal_id,
                candidate_id,
                "canary_running",
                artifact=artifact,
                evidence=evidence,
                promotion=promotion,
                canary=canary,
            )
        except Exception:
            try:
                self.bridge.release_candidate(candidate_id, outcome="cancelled")
            except (KeyError, ValueError):
                pass
            raise

    def snapshot(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            proposal_rows = conn.execute(
                "SELECT status, COUNT(*) AS total FROM improvement_proposals GROUP BY status"
            ).fetchall()
            link_rows = conn.execute(
                "SELECT status, COUNT(*) AS total FROM improvement_candidate_links GROUP BY status"
            ).fetchall()
            canary_rows = conn.execute(
                "SELECT status, COUNT(*) AS total FROM improvement_canaries GROUP BY status"
            ).fetchall()
        return {
            "proposals": {row["status"]: row["total"] for row in proposal_rows},
            "candidate_links": {row["status"]: row["total"] for row in link_rows},
            "canaries": {row["status"]: row["total"] for row in canary_rows},
            "resource_usage": self.bridge.resource_usage(),
        }

    def export(self, proposal_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            proposal = conn.execute(
                "SELECT status, payload_json FROM improvement_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if proposal is None:
                raise KeyError(f"propuesta no registrada: {proposal_id}")
            links = [
                dict(row)
                for row in conn.execute(
                    """SELECT candidate_id, neuron_id, version, status, resource_json
                    FROM improvement_candidate_links WHERE proposal_id = ? ORDER BY candidate_id""",
                    (proposal_id,),
                ).fetchall()
            ]
            canaries = [
                json.loads(row["payload_json"])
                for row in conn.execute(
                    """SELECT c.payload_json FROM improvement_canaries c
                    JOIN improvement_candidate_links l ON l.candidate_id = c.candidate_id
                    WHERE l.proposal_id = ? ORDER BY c.canary_id""",
                    (proposal_id,),
                ).fetchall()
            ]
        document = {
            "schema_version": "1.0.0",
            "proposal_id": proposal_id,
            "proposal_status": proposal["status"],
            "proposal": json.loads(proposal["payload_json"]),
            "candidate_links": links,
            "canaries": canaries,
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
        document["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return document

    def _proposal(self, proposal_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT payload_json, status FROM improvement_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"propuesta no registrada: {proposal_id}")
        return {**json.loads(row["payload_json"]), "status": row["status"]}

    def _result(self, proposal_id: str, candidate_id: str, status: str, **parts: Any) -> dict[str, Any]:
        result = {
            "proposal_id": proposal_id,
            "candidate_id": candidate_id,
            "status": status,
            **parts,
        }
        canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
        result["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return result
