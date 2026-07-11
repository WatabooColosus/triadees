"""Gate persistente de no-regresión para Tríade Ω."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now
from triade.evaluation import EvaluationRun

Severity = Literal["critical", "high", "medium", "low"]
GateDecision = Literal["pass", "warn", "fail", "invalid"]


@dataclass(frozen=True, slots=True)
class MetricPolicy:
    """Umbral reproducible para una métrica protegida."""

    metric_id: str
    severity: Severity = "medium"
    max_absolute_drop: float = 0.0
    max_relative_drop: float = 0.0
    required: bool = True

    def __post_init__(self) -> None:
        if not self.metric_id.strip():
            raise ValueError("metric_id es obligatorio")
        if self.severity not in {"critical", "high", "medium", "low"}:
            raise ValueError("severity inválida")
        if self.max_absolute_drop < 0 or self.max_relative_drop < 0:
            raise ValueError("las tolerancias no pueden ser negativas")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RegressionFinding:
    metric_id: str
    severity: Severity
    baseline_score: float | None
    candidate_score: float | None
    absolute_delta: float | None
    relative_delta: float | None
    status: GateDecision
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RegressionReport:
    report_id: str
    candidate_id: str
    capability: str
    suite_id: str
    suite_version: str
    baseline_evaluation_id: str
    candidate_evaluation_id: str
    decision: GateDecision
    findings: tuple[RegressionFinding, ...]
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking_findings(self) -> tuple[RegressionFinding, ...]:
        return tuple(f for f in self.findings if f.status in {"fail", "invalid"})

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blocking_findings"] = [f.to_dict() for f in self.blocking_findings]
        return payload


class RegressionGate:
    """Compara evaluaciones y persiste decisiones, cuarentena y rollback lógico."""

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
                """CREATE TABLE IF NOT EXISTS regression_reports (
                    report_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    suite_id TEXT NOT NULL,
                    suite_version TEXT NOT NULL,
                    baseline_evaluation_id TEXT NOT NULL,
                    candidate_evaluation_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    findings_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS regression_quarantine (
                    candidate_id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    quarantined_at TEXT NOT NULL,
                    released_at TEXT
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS stable_capability_state (
                    capability TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    evaluation_id TEXT NOT NULL,
                    suite_id TEXT NOT NULL,
                    suite_version TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )"""
            )

    @staticmethod
    def _results_by_case(run: EvaluationRun) -> dict[str, float]:
        return {result.case_id: float(result.score) for result in run.results}

    def evaluate(
        self,
        *,
        report_id: str,
        candidate_id: str,
        capability: str,
        baseline: EvaluationRun,
        candidate: EvaluationRun,
        policies: tuple[MetricPolicy, ...],
        metadata: dict[str, Any] | None = None,
    ) -> RegressionReport:
        if not all((report_id.strip(), candidate_id.strip(), capability.strip())):
            raise ValueError("report_id, candidate_id y capability son obligatorios")
        if not policies:
            raise ValueError("se requiere al menos una política de métrica")
        if baseline.suite_id != candidate.suite_id or baseline.suite_version != candidate.suite_version:
            decision: GateDecision = "invalid"
            findings = (
                RegressionFinding(
                    metric_id="suite_compatibility",
                    severity="critical",
                    baseline_score=None,
                    candidate_score=None,
                    absolute_delta=None,
                    relative_delta=None,
                    status="invalid",
                    reason="baseline y candidate usan suites o versiones incompatibles",
                ),
            )
        else:
            baseline_scores = self._results_by_case(baseline)
            candidate_scores = self._results_by_case(candidate)
            built: list[RegressionFinding] = []
            for policy in policies:
                before = baseline_scores.get(policy.metric_id)
                after = candidate_scores.get(policy.metric_id)
                if before is None or after is None:
                    status: GateDecision = "invalid" if policy.required else "warn"
                    built.append(
                        RegressionFinding(
                            metric_id=policy.metric_id,
                            severity=policy.severity,
                            baseline_score=before,
                            candidate_score=after,
                            absolute_delta=None,
                            relative_delta=None,
                            status=status,
                            reason="métrica requerida ausente" if policy.required else "métrica opcional ausente",
                        )
                    )
                    continue
                absolute_delta = after - before
                relative_delta = None if before == 0 else absolute_delta / before
                absolute_drop = max(0.0, -absolute_delta)
                relative_drop = max(0.0, -(relative_delta or 0.0))
                exceeded = (
                    absolute_drop > policy.max_absolute_drop
                    or relative_drop > policy.max_relative_drop
                )
                if exceeded:
                    status = "fail" if policy.severity in {"critical", "high"} else "warn"
                    reason = "caída supera el umbral de no-regresión"
                else:
                    status = "pass"
                    reason = "métrica dentro del umbral permitido"
                built.append(
                    RegressionFinding(
                        metric_id=policy.metric_id,
                        severity=policy.severity,
                        baseline_score=before,
                        candidate_score=after,
                        absolute_delta=absolute_delta,
                        relative_delta=relative_delta,
                        status=status,
                        reason=reason,
                    )
                )
            findings = tuple(built)
            if any(f.status in {"fail", "invalid"} for f in findings):
                decision = "fail" if any(f.status == "fail" for f in findings) else "invalid"
            elif any(f.status == "warn" for f in findings):
                decision = "warn"
            else:
                decision = "pass"

        report = RegressionReport(
            report_id=report_id,
            candidate_id=candidate_id,
            capability=capability,
            suite_id=candidate.suite_id,
            suite_version=candidate.suite_version,
            baseline_evaluation_id=baseline.evaluation_id,
            candidate_evaluation_id=candidate.evaluation_id,
            decision=decision,
            findings=findings,
            created_at=utc_now(),
            metadata=dict(metadata or {}),
        )
        self._persist(report)
        if report.decision in {"fail", "invalid"}:
            self.quarantine(candidate_id, report.report_id, self._blocking_reason(report))
        return report

    @staticmethod
    def _blocking_reason(report: RegressionReport) -> str:
        return "; ".join(f"{f.metric_id}: {f.reason}" for f in report.blocking_findings)

    def _persist(self, report: RegressionReport) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO regression_reports
                (report_id, candidate_id, capability, suite_id, suite_version,
                 baseline_evaluation_id, candidate_evaluation_id, decision,
                 findings_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.report_id,
                    report.candidate_id,
                    report.capability,
                    report.suite_id,
                    report.suite_version,
                    report.baseline_evaluation_id,
                    report.candidate_evaluation_id,
                    report.decision,
                    json.dumps([f.to_dict() for f in report.findings], ensure_ascii=False),
                    json.dumps(report.metadata, ensure_ascii=False),
                    report.created_at,
                ),
            )

    def quarantine(self, candidate_id: str, report_id: str, reason: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO regression_quarantine
                (candidate_id, report_id, reason, active, quarantined_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    report_id=excluded.report_id,
                    reason=excluded.reason,
                    active=1,
                    quarantined_at=excluded.quarantined_at,
                    released_at=NULL""",
                (candidate_id, report_id, reason, utc_now()),
            )

    def require_pass(self, candidate_id: str) -> RegressionReport:
        report = self.latest_for_candidate(candidate_id)
        if report is None:
            raise ValueError("No existe reporte de regresión para el candidato")
        if report.decision != "pass":
            raise ValueError(f"Regression Gate bloquea el candidato: decision={report.decision}")
        if self.is_quarantined(candidate_id):
            raise ValueError("El candidato continúa en cuarentena")
        return report

    def is_quarantined(self, candidate_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT active FROM regression_quarantine WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return bool(row and row["active"])

    def release_quarantine(self, candidate_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE regression_quarantine
                SET active=0, released_at=? WHERE candidate_id=?""",
                (utc_now(), candidate_id),
            )

    def record_stable_state(self, capability: str, evaluation: EvaluationRun) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO stable_capability_state
                (capability, subject_id, evaluation_id, suite_id, suite_version, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability) DO UPDATE SET
                    subject_id=excluded.subject_id,
                    evaluation_id=excluded.evaluation_id,
                    suite_id=excluded.suite_id,
                    suite_version=excluded.suite_version,
                    recorded_at=excluded.recorded_at""",
                (
                    capability,
                    evaluation.subject_id,
                    evaluation.evaluation_id,
                    evaluation.suite_id,
                    evaluation.suite_version,
                    utc_now(),
                ),
            )

    def rollback_target(self, capability: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM stable_capability_state WHERE capability = ?",
                (capability,),
            ).fetchone()
        return dict(row) if row else None

    def latest_for_candidate(self, candidate_id: str) -> RegressionReport | None:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM regression_reports
                WHERE candidate_id = ? ORDER BY created_at DESC, report_id DESC LIMIT 1""",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        findings = tuple(RegressionFinding(**item) for item in json.loads(row["findings_json"]))
        return RegressionReport(
            report_id=row["report_id"],
            candidate_id=row["candidate_id"],
            capability=row["capability"],
            suite_id=row["suite_id"],
            suite_version=row["suite_version"],
            baseline_evaluation_id=row["baseline_evaluation_id"],
            candidate_evaluation_id=row["candidate_evaluation_id"],
            decision=row["decision"],
            findings=findings,
            created_at=row["created_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
