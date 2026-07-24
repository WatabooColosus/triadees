"""Consejo Autónomo de Verificación de Tríade Ω.

Operación independiente del pipeline de aprendizaje.
Múltiples verificadores independientes emiten veredictos.
Ningún componente se auto-verifica (Artículo V de la Constitución).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

Verdict = Literal["approved", "rejected", "conditional", "pending"]


@dataclass(frozen=True, slots=True)
class VerifierOpinion:
    verifier_id: str
    verifier_type: str
    verdict: Verdict
    confidence: float
    reasoning: str
    evidence_refs: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CouncilDecision:
    decision_id: str
    target_capability: str
    target_candidate: str | None
    opinions: tuple[VerifierOpinion, ...]
    final_verdict: Verdict
    score: float
    reasoning_summary: str
    created_at: str
    appeal_deadline: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VerificationCouncil:
    """Consejo autónomo con verificadores independientes."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._verifiers: list[str] = []
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS council_decisions (
                    decision_id TEXT PRIMARY KEY,
                    target_capability TEXT NOT NULL,
                    target_candidate TEXT,
                    opinions_json TEXT NOT NULL,
                    final_verdict TEXT NOT NULL,
                    score REAL NOT NULL,
                    reasoning_summary TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    appeal_deadline TEXT
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_council_capability ON council_decisions(target_capability)"
            )

    def register_verifier(self, verifier_id: str) -> None:
        if verifier_id not in self._verifiers:
            self._verifiers.append(verifier_id)

    def convene(
        self,
        *,
        decision_id: str,
        target_capability: str,
        target_candidate: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> CouncilDecision:
        ctx = context or {}
        opinions: list[VerifierOpinion] = []
        for verifier_id in self._verifiers:
            opinion = self._gather_opinion(verifier_id, target_capability, ctx)
            opinions.append(opinion)
        if not opinions:
            opinions = [
                VerifierOpinion(
                    verifier_id="default-safety",
                    verifier_type="safety",
                    verdict="conditional",
                    confidence=0.5,
                    reasoning="Sin verificadores registrados; veredicto condicional por defecto.",
                    conditions=("Registrar al menos un verificador.",),
                )
            ]
        final = self._aggregate_verdicts(opinions)
        score = self._compute_score(opinions)
        reasoning = self._build_reasoning_summary(opinions, final)
        decision = CouncilDecision(
            decision_id=decision_id,
            target_capability=target_capability,
            target_candidate=target_candidate,
            opinions=tuple(opinions),
            final_verdict=final,
            score=score,
            reasoning_summary=reasoning,
            created_at=utc_now(),
        )
        self._persist(decision)
        return decision

    def _gather_opinion(
        self, verifier_id: str, capability: str, context: dict[str, Any]
    ) -> VerifierOpinion:
        has_baseline = context.get("has_baseline", False)
        has_rollback = context.get("has_rollback", False)
        regression_pass = context.get("regression_pass", None)
        critical_issues = context.get("critical_issues", [])

        if "safety" in verifier_id.lower():
            if critical_issues:
                return VerifierOpinion(
                    verifier_id=verifier_id, verifier_type="safety",
                    verdict="rejected", confidence=0.9,
                    reasoning=f"Problemas críticos detectados: {critical_issues}",
                )
            return VerifierOpinion(
                verifier_id=verifier_id, verifier_type="safety",
                verdict="approved" if has_rollback else "conditional",
                confidence=0.8 if has_rollback else 0.6,
                reasoning="Sin problemas críticos." + (" Rollback registrado." if has_rollback else " Falta rollback."),
                conditions=() if has_rollback else ("Registrar rollback.",),
            )
        if "regression" in verifier_id.lower():
            if regression_pass is False:
                return VerifierOpinion(
                    verifier_id=verifier_id, verifier_type="regression",
                    verdict="rejected", confidence=0.95,
                    reasoning="Regression Gate reporta fallo.",
                )
            if regression_pass is True:
                return VerifierOpinion(
                    verifier_id=verifier_id, verifier_type="regression",
                    verdict="approved", confidence=0.9,
                    reasoning="Regression Gate reporta pass.",
                )
            return VerifierOpinion(
                verdict="conditional", confidence=0.5,
                verifier_id=verifier_id, verifier_type="regression",
                reasoning="Sin evidencia de Regression Gate.",
                conditions=("Ejecutar Regression Gate.",),
            )
        if "evidence" in verifier_id.lower():
            if has_baseline:
                return VerifierOpinion(
                    verifier_id=verifier_id, verifier_type="evidence",
                    verdict="approved", confidence=0.8,
                    reasoning="Baseline existe para la capacidad.",
                )
            return VerifierOpinion(
                verifier_id=verifier_id, verifier_type="evidence",
                verdict="conditional", confidence=0.5,
                reasoning="Sin baseline registrado.",
                conditions=("Crear baseline antes de promover.",),
            )
        return VerifierOpinion(
            verifier_id=verifier_id, verifier_type="generic",
            verdict="conditional", confidence=0.5,
            reasoning=f"Verificador '{verifier_id}' sin reglas específicas.",
        )

    @staticmethod
    def _aggregate_verdicts(opinions: list[VerifierOpinion]) -> Verdict:
        verdicts = [o.verdict for o in opinions]
        if "rejected" in verdicts:
            return "rejected"
        if all(v == "approved" for v in verdicts):
            return "approved"
        if "conditional" in verdicts:
            return "conditional"
        return "pending"

    @staticmethod
    def _compute_score(opinions: list[VerifierOpinion]) -> float:
        if not opinions:
            return 0.0
        weights = {"approved": 1.0, "conditional": 0.5, "rejected": 0.0, "pending": 0.3}
        total = sum(weights.get(o.verdict, 0.3) * o.confidence for o in opinions)
        return round(total / len(opinions), 3)

    @staticmethod
    def _build_reasoning_summary(opinions: list[VerifierOpinion], final: Verdict) -> str:
        approved = sum(1 for o in opinions if o.verdict == "approved")
        rejected = sum(1 for o in opinions if o.verdict == "rejected")
        conditional = sum(1 for o in opinions if o.verdict == "conditional")
        return (
            f"Consejo: {len(opinions)} verificadores. "
            f"Aprobados={approved}, Rechazados={rejected}, Condicionales={conditional}. "
            f"Veredicto final={final}."
        )

    def _persist(self, decision: CouncilDecision) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO council_decisions
                (decision_id, target_capability, target_candidate, opinions_json,
                 final_verdict, score, reasoning_summary, created_at, appeal_deadline)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision.decision_id,
                    decision.target_capability,
                    decision.target_candidate,
                    json.dumps([o.to_dict() for o in decision.opinions], ensure_ascii=False),
                    decision.final_verdict,
                    decision.score,
                    decision.reasoning_summary,
                    decision.created_at,
                    decision.appeal_deadline,
                ),
            )

    def get_decision(self, decision_id: str) -> CouncilDecision | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM council_decisions WHERE decision_id = ?", (decision_id,)
            ).fetchone()
        if row is None:
            return None
        opinions = tuple(VerifierOpinion(**o) for o in json.loads(row["opinions_json"]))
        return CouncilDecision(
            decision_id=row["decision_id"],
            target_capability=row["target_capability"],
            target_candidate=row["target_candidate"],
            opinions=opinions,
            final_verdict=row["final_verdict"],
            score=row["score"],
            reasoning_summary=row["reasoning_summary"],
            created_at=row["created_at"],
            appeal_deadline=row["appeal_deadline"],
        )

    def history(self, capability: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT decision_id, final_verdict, score, created_at FROM council_decisions WHERE target_capability = ? ORDER BY created_at DESC",
                (capability,),
            ).fetchall()
        return [dict(row) for row in rows]

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM council_decisions").fetchone()["c"]
            approved = conn.execute("SELECT COUNT(*) as c FROM council_decisions WHERE final_verdict='approved'").fetchone()["c"]
            rejected = conn.execute("SELECT COUNT(*) as c FROM council_decisions WHERE final_verdict='rejected'").fetchone()["c"]
        return {
            "total_decisions": total,
            "approved": approved,
            "rejected": rejected,
            "registered_verifiers": list(self._verifiers),
            "constitution_version": "1.0.0",
        }
