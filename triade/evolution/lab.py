"""Ciclo medible y reversible de evolución.

Este módulo no afirma producir IAG. Obliga a que cualquier cambio pase por seis
etapas con evidencia persistida: batería congelada, aprendizaje reproducible,
adaptador, investigación, autonomía prolongada y evaluación externa.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


class Stage(IntEnum):
    MEASUREMENT = 1
    EXPERIENCE = 2
    ADAPTER = 3
    RESEARCH = 4
    LONG_HORIZON = 5
    EXTERNAL_EVALUATION = 6


@dataclass(frozen=True, slots=True)
class EvolutionPolicy:
    required_domains: tuple[str, ...] = (
        "reasoning",
        "code",
        "mathematics",
        "science",
        "planning",
        "longitudinal_memory",
        "social_understanding",
        "causality",
        "safety",
        "tool_use",
        "rule_adaptation",
        "long_horizon",
    )
    minimum_domain_score: float = 0.70
    minimum_overall_score: float = 0.75
    minimum_improvement: float = 0.02
    maximum_regression: float = 0.03
    minimum_transfer_contexts: int = 3
    minimum_independent_evidence: int = 2
    minimum_canary_observations: int = 3
    minimum_long_horizon_checkpoints: int = 3
    maximum_daily_gpu_minutes: int = 120
    maximum_daily_experiments: int = 12
    maximum_storage_mb: int = 4096


@dataclass(frozen=True, slots=True)
class StageDecision:
    stage: Stage
    passed: bool
    reasons: tuple[str, ...]
    metrics: dict[str, Any]
    evidence_hash: str


SCHEMA = """
CREATE TABLE IF NOT EXISTS evolution_campaigns (
  campaign_id TEXT PRIMARY KEY, title TEXT NOT NULL, hypothesis TEXT NOT NULL,
  baseline_version TEXT NOT NULL, candidate_version TEXT NOT NULL,
  stage INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
  policy_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evolution_evidence (
  evidence_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, stage INTEGER NOT NULL,
  kind TEXT NOT NULL, payload_json TEXT NOT NULL, payload_hash TEXT NOT NULL,
  source TEXT NOT NULL, independent INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(campaign_id) REFERENCES evolution_campaigns(campaign_id)
);
CREATE TABLE IF NOT EXISTS frozen_batteries (
  battery_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, manifest_hash TEXT NOT NULL,
  domains_json TEXT NOT NULL, case_hashes_json TEXT NOT NULL,
  sealed INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evolution_stage_decisions (
  decision_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, stage INTEGER NOT NULL,
  passed INTEGER NOT NULL, reasons_json TEXT NOT NULL, metrics_json TEXT NOT NULL,
  evidence_hash TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evolution_resource_ledger (
  entry_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, gpu_minutes REAL DEFAULT 0,
  experiments INTEGER DEFAULT 0, storage_mb REAL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evolution_artifacts (
  artifact_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, kind TEXT NOT NULL,
  path TEXT NOT NULL, sha256 TEXT NOT NULL, parent_sha256 TEXT,
  status TEXT NOT NULL DEFAULT 'candidate', metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


class EvolutionLab:
    """Gate único para campañas de mejora, sin promoción recursiva automática."""

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        signing_key: bytes | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.signing_key = signing_key
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def create_campaign(
        self,
        title: str,
        hypothesis: str,
        baseline_version: str,
        candidate_version: str,
        policy: EvolutionPolicy | None = None,
    ) -> dict[str, Any]:
        if baseline_version == candidate_version:
            raise ValueError("baseline y candidate deben ser versiones distintas")
        p = policy or EvolutionPolicy()
        campaign_id = f"evo-{uuid.uuid4().hex[:16]}"
        now = _now()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evolution_campaigns VALUES (?,?,?,?,?,1,'active',?,?,?)",
                (
                    campaign_id,
                    title,
                    hypothesis,
                    baseline_version,
                    candidate_version,
                    _canonical(asdict(p)),
                    now,
                    now,
                ),
            )
        return self.campaign(campaign_id)

    def campaign(self, campaign_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evolution_campaigns WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
        if row is None:
            raise KeyError(campaign_id)
        result = dict(row)
        result["policy"] = json.loads(result.pop("policy_json"))
        result["stage_name"] = Stage(result["stage"]).name.lower()
        return result

    def freeze_battery(
        self, campaign_id: str, cases: Iterable[dict[str, Any]]
    ) -> dict[str, Any]:
        campaign = self.campaign(campaign_id)
        if campaign["stage"] != Stage.MEASUREMENT:
            raise ValueError("la batería solo puede congelarse en etapa 1")
        material = list(cases)
        if not material:
            raise ValueError("la batería no puede estar vacía")
        domains = sorted(
            {str(case.get("domain", "")) for case in material if case.get("domain")}
        )
        missing = sorted(set(campaign["policy"]["required_domains"]) - set(domains))
        if missing:
            raise ValueError(f"faltan dominios obligatorios: {', '.join(missing)}")
        case_hashes = [_sha(case) for case in material]
        manifest = {
            "domains": domains,
            "case_hashes": case_hashes,
            "count": len(material),
        }
        battery_id = f"battery-{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO frozen_batteries VALUES (?,?,?,?,?,1,?)",
                (
                    battery_id,
                    campaign_id,
                    _sha(manifest),
                    _canonical(domains),
                    _canonical(case_hashes),
                    _now(),
                ),
            )
        return {
            "battery_id": battery_id,
            "manifest_hash": _sha(manifest),
            "domains": domains,
            "case_count": len(case_hashes),
            "sealed": True,
        }

    def record_evidence(
        self,
        campaign_id: str,
        stage: Stage,
        kind: str,
        payload: dict[str, Any],
        *,
        source: str,
        independent: bool = False,
    ) -> dict[str, Any]:
        campaign = self.campaign(campaign_id)
        if int(stage) > campaign["stage"]:
            raise ValueError("no se puede registrar evidencia de una etapa futura")
        evidence_id = f"evidence-{uuid.uuid4().hex[:16]}"
        digest = _sha(payload)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evolution_evidence VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    evidence_id,
                    campaign_id,
                    int(stage),
                    kind,
                    _canonical(payload),
                    digest,
                    source,
                    int(independent),
                    _now(),
                ),
            )
        return {
            "evidence_id": evidence_id,
            "payload_hash": digest,
            "independent": independent,
        }

    def register_artifact(
        self,
        campaign_id: str,
        kind: str,
        path: str | Path,
        *,
        parent_sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        artifact_path = Path(path)
        if not artifact_path.is_file():
            raise ValueError("el artefacto debe existir y ser un archivo")
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        artifact_id = f"artifact-{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evolution_artifacts VALUES (?,?,?,?,?,?,'candidate',?,?)",
                (
                    artifact_id,
                    campaign_id,
                    kind,
                    str(artifact_path),
                    digest,
                    parent_sha256,
                    _canonical(metadata or {}),
                    _now(),
                ),
            )
        return {"artifact_id": artifact_id, "sha256": digest, "status": "candidate"}

    def charge_resources(
        self,
        campaign_id: str,
        *,
        gpu_minutes: float = 0,
        experiments: int = 0,
        storage_mb: float = 0,
    ) -> dict[str, Any]:
        if min(gpu_minutes, experiments, storage_mb) < 0:
            raise ValueError("los consumos no pueden ser negativos")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evolution_resource_ledger VALUES (?,?,?,?,?,?)",
                (
                    f"usage-{uuid.uuid4().hex[:12]}",
                    campaign_id,
                    gpu_minutes,
                    experiments,
                    storage_mb,
                    _now(),
                ),
            )
            row = conn.execute(
                "SELECT COALESCE(SUM(gpu_minutes),0) gpu, COALESCE(SUM(experiments),0) exp, "
                "COALESCE(SUM(storage_mb),0) storage FROM evolution_resource_ledger WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()
        usage = {
            "gpu_minutes": row["gpu"],
            "experiments": row["exp"],
            "storage_mb": row["storage"],
        }
        policy = self.campaign(campaign_id)["policy"]
        usage["within_budget"] = (
            usage["gpu_minutes"] <= policy["maximum_daily_gpu_minutes"]
            and usage["experiments"] <= policy["maximum_daily_experiments"]
            and usage["storage_mb"] <= policy["maximum_storage_mb"]
        )
        return usage

    def evaluate_stage(self, campaign_id: str) -> StageDecision:
        campaign = self.campaign(campaign_id)
        stage = Stage(campaign["stage"])
        evidence = self._evidence(campaign_id, stage)
        policy = campaign["policy"]
        reasons: list[str] = []
        metrics: dict[str, Any] = {"evidence_count": len(evidence)}

        if stage == Stage.MEASUREMENT:
            with self._connect() as conn:
                battery = conn.execute(
                    "SELECT * FROM frozen_batteries WHERE campaign_id=?", (campaign_id,)
                ).fetchone()
            if battery is None:
                reasons.append("falta batería congelada")
            comparison = self._latest_payload(evidence, "baseline_comparison")
            if not comparison:
                reasons.append("falta comparación baseline/candidate")
            else:
                scores = comparison.get("candidate_scores", {})
                missing = set(policy["required_domains"]) - set(scores)
                low = {
                    k: v
                    for k, v in scores.items()
                    if float(v) < policy["minimum_domain_score"]
                }
                overall = float(comparison.get("candidate_overall", 0))
                improvement = overall - float(comparison.get("baseline_overall", 0))
                regressions = comparison.get("regressions", {})
                metrics.update(
                    {
                        "overall": overall,
                        "improvement": improvement,
                        "low_domains": low,
                        "missing_domains": sorted(missing),
                        "regressions": regressions,
                    }
                )
                if missing or low:
                    reasons.append("cobertura o score de dominios insuficiente")
                if overall < policy["minimum_overall_score"]:
                    reasons.append("score global insuficiente")
                if improvement < policy["minimum_improvement"]:
                    reasons.append("mejora contra baseline insuficiente")
                if any(
                    abs(float(v)) > policy["maximum_regression"]
                    for v in regressions.values()
                ):
                    reasons.append("regresión superior al límite")
        elif stage == Stage.EXPERIENCE:
            lessons = [e for e in evidence if e["kind"] == "reproducible_lesson"]
            independent = sum(e["independent"] for e in evidence)
            contexts = {
                p
                for e in evidence
                for p in json.loads(e["payload_json"]).get("transfer_contexts", [])
            }
            metrics.update(
                {
                    "lessons": len(lessons),
                    "independent_evidence": independent,
                    "transfer_contexts": len(contexts),
                }
            )
            if not lessons:
                reasons.append("falta lección reproducible")
            if independent < policy["minimum_independent_evidence"]:
                reasons.append("evidencia independiente insuficiente")
            if len(contexts) < policy["minimum_transfer_contexts"]:
                reasons.append("transferencia insuficiente")
        elif stage == Stage.ADAPTER:
            required = {
                "dataset_split",
                "adapter_training",
                "ood_evaluation",
                "forgetting_evaluation",
                "canary",
            }
            present = {e["kind"] for e in evidence}
            metrics["present"] = sorted(present)
            if required - present:
                reasons.append(
                    f"faltan controles de adaptador: {sorted(required - present)}"
                )
            canary = self._latest_payload(evidence, "canary") or {}
            if (
                int(canary.get("observations", 0))
                < policy["minimum_canary_observations"]
            ):
                reasons.append("canary insuficiente")
            if not canary.get("rollback_ready", False):
                reasons.append("rollback no demostrado")
            if not self._has_artifact(campaign_id, "adapter"):
                reasons.append("falta artefacto de adaptador firmado")
        elif stage == Stage.RESEARCH:
            cycle = self._latest_payload(evidence, "scientific_cycle") or {}
            required = {
                "question",
                "sources",
                "hypothesis",
                "prediction",
                "experiment",
                "result",
                "refutation",
                "update",
            }
            missing_fields = sorted(k for k in required if not cycle.get(k))
            metrics["missing_fields"] = missing_fields
            if missing_fields:
                reasons.append("ciclo científico incompleto")
            if any(
                not s.get("url") or not s.get("retrieved_at")
                for s in cycle.get("sources", [])
            ):
                reasons.append("fuentes sin procedencia o fecha")
            if cycle.get("memory_status") not in {"candidate", "rejected"}:
                reasons.append(
                    "investigación no puede entrar directamente como memoria estable"
                )
        elif stage == Stage.LONG_HORIZON:
            run = self._latest_payload(evidence, "long_horizon_run") or {}
            checkpoints = run.get("checkpoints", [])
            metrics.update(
                {
                    "checkpoints": len(checkpoints),
                    "replans": run.get("replans", 0),
                    "recovered_after_restart": run.get(
                        "recovered_after_restart", False
                    ),
                }
            )
            if len(checkpoints) < policy["minimum_long_horizon_checkpoints"]:
                reasons.append("checkpoints insuficientes")
            if not run.get("stagnation_detection", False):
                reasons.append("falta detección de estancamiento")
            if not run.get("uncertainty_estimation", False):
                reasons.append("falta estimación de incertidumbre")
            if not run.get("recovered_after_restart", False):
                reasons.append("recuperación tras reinicio no demostrada")
            if not self.charge_resources(campaign_id)["within_budget"]:
                reasons.append("presupuesto excedido")
        else:
            reports = [
                e
                for e in evidence
                if e["kind"] == "external_report" and e["independent"]
            ]
            metrics["external_reports"] = len(reports)
            valid = [
                e
                for e in reports
                if self._valid_external_report(json.loads(e["payload_json"]))
            ]
            metrics["valid_reports"] = len(valid)
            if len(valid) < policy["minimum_independent_evidence"]:
                reasons.append("faltan evaluaciones externas independientes y firmadas")

        decision = StageDecision(
            stage,
            not reasons,
            tuple(reasons),
            metrics,
            _sha([e["payload_hash"] for e in evidence]),
        )
        self._persist_decision(campaign_id, decision)
        return decision

    def advance(self, campaign_id: str) -> dict[str, Any]:
        decision = self.evaluate_stage(campaign_id)
        if not decision.passed:
            return {"advanced": False, "decision": self._decision_dict(decision)}
        campaign = self.campaign(campaign_id)
        if campaign["stage"] == Stage.EXTERNAL_EVALUATION:
            next_stage, status = campaign["stage"], "validated"
        else:
            next_stage, status = campaign["stage"] + 1, "active"
        with self._connect() as conn:
            conn.execute(
                "UPDATE evolution_campaigns SET stage=?, status=?, updated_at=? WHERE campaign_id=?",
                (next_stage, status, _now(), campaign_id),
            )
        return {
            "advanced": True,
            "campaign": self.campaign(campaign_id),
            "decision": self._decision_dict(decision),
        }

    def reject(self, campaign_id: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("se requiere una razón")
        self.record_evidence(
            campaign_id,
            Stage(self.campaign(campaign_id)["stage"]),
            "rejection",
            {"reason": reason},
            source="governance",
        )
        with self._connect() as conn:
            conn.execute(
                "UPDATE evolution_campaigns SET status='rejected', updated_at=? WHERE campaign_id=?",
                (_now(), campaign_id),
            )
            conn.execute(
                "UPDATE evolution_artifacts SET status='rejected' WHERE campaign_id=?",
                (campaign_id,),
            )
        return self.campaign(campaign_id)

    def report(self, campaign_id: str) -> dict[str, Any]:
        campaign = self.campaign(campaign_id)
        with self._connect() as conn:
            decisions = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM evolution_stage_decisions WHERE campaign_id=? ORDER BY created_at",
                    (campaign_id,),
                )
            ]
            artifacts = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM evolution_artifacts WHERE campaign_id=? ORDER BY created_at",
                    (campaign_id,),
                )
            ]
        body = {
            "campaign": campaign,
            "decisions": decisions,
            "artifacts": artifacts,
            "resource_usage": self.charge_resources(campaign_id),
        }
        body["sha256"] = _sha(body)
        if self.signing_key:
            body["signature"] = hmac.new(
                self.signing_key, str(body["sha256"]).encode(), hashlib.sha256
            ).hexdigest()
        return body

    def _evidence(self, campaign_id: str, stage: Stage) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM evolution_evidence WHERE campaign_id=? AND stage=? ORDER BY created_at",
                    (campaign_id, int(stage)),
                )
            ]

    @staticmethod
    def _latest_payload(
        evidence: list[dict[str, Any]], kind: str
    ) -> dict[str, Any] | None:
        matches = [json.loads(e["payload_json"]) for e in evidence if e["kind"] == kind]
        return matches[-1] if matches else None

    def _has_artifact(self, campaign_id: str, kind: str) -> bool:
        with self._connect() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM evolution_artifacts WHERE campaign_id=? AND kind=?",
                    (campaign_id, kind),
                ).fetchone()
                is not None
            )

    def _valid_external_report(self, payload: dict[str, Any]) -> bool:
        required = {"evaluator", "suite", "score", "report_hash", "signature"}
        return (
            required <= payload.keys()
            and bool(payload.get("evaluator"))
            and 0 <= float(payload.get("score", -1)) <= 1
        )

    def _persist_decision(self, campaign_id: str, decision: StageDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evolution_stage_decisions VALUES (?,?,?,?,?,?,?,?)",
                (
                    f"decision-{uuid.uuid4().hex[:12]}",
                    campaign_id,
                    int(decision.stage),
                    int(decision.passed),
                    _canonical(decision.reasons),
                    _canonical(decision.metrics),
                    decision.evidence_hash,
                    _now(),
                ),
            )

    @staticmethod
    def _decision_dict(decision: StageDecision) -> dict[str, Any]:
        return {
            "stage": int(decision.stage),
            "stage_name": decision.stage.name.lower(),
            "passed": decision.passed,
            "reasons": list(decision.reasons),
            "metrics": decision.metrics,
            "evidence_hash": decision.evidence_hash,
        }
