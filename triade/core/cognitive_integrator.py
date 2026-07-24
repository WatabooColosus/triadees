"""Integrador Cognitivo — Flujo E2E completo gobernado.

Flujo:
InputPacket → Bodega (memoria) → Hipotálamo (señales) → Qualia (experiencia) →
Cristal (continuidad/identidad) → Constitución (restricciones) → Central (plan) →
Resolución de conflictos (7 tipos) → Decisión → Trazabilidad completa.

7 tipos de conflicto:
1. priority_vs_resources
2. curiosity_vs_safety
3. speed_vs_precision
4. learning_vs_stability
5. purpose_vs_request
6. identity_vs_modification
7. autonomy_vs_constitution
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from triade.core.contracts import utc_now
from triade.core.constitution import Constitution, GLOBAL_CONSTITUTION

log = logging.getLogger(__name__)


@runtime_checkable
class CentralLike(Protocol):
    steps: list[Any]
    structured_steps: list[Any] | None
    rollback: Any | None
    total_budget_cpu: float
    total_budget_ram: float
    constitution_applied: list[dict[str, Any]]
    def extract_subgraph(self, max_steps: int) -> list[Any]: ...


@runtime_checkable
class HypothalamusLike(Protocol):
    urgency: str
    risk: str
    curiosity: float
    notes: list[str]
    def to_dict(self) -> dict[str, Any]: ...


@runtime_checkable
class CrystalLike(Protocol):
    q_crystal: float
    temporal_status: str

log = logging.getLogger(__name__)

CONFLICT_TYPES = (
    "priority_vs_resources",
    "curiosity_vs_safety",
    "speed_vs_precision",
    "learning_vs_stability",
    "purpose_vs_request",
    "identity_vs_modification",
    "autonomy_vs_constitution",
)

CONFLICT_RESOLUTION_STRATEGIES: dict[str, str] = {
    "priority_vs_resources": "reduce_scope",
    "curiosity_vs_safety": "safety_wins",
    "speed_vs_precision": "precision_wins",
    "learning_vs_stability": "stability_wins",
    "purpose_vs_request": "purpose_wins",
    "identity_vs_modification": "identity_wins",
    "autonomy_vs_constitution": "constitution_wins",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS integrated_decisions (
    decision_id    TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    conflicts_json TEXT NOT NULL DEFAULT '[]',
    constitution_json TEXT NOT NULL DEFAULT '[]',
    trace_json     TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS id_run ON integrated_decisions(run_id);
"""


@dataclass(slots=True)
class ConflictRecord:
    conflict_type: str = ""
    source_a: str = ""
    source_b: str = ""
    field_name: str = ""
    value_a: Any = None
    value_b: Any = None
    resolution: str = ""
    strategy: str = ""
    severity: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_type": self.conflict_type,
            "source_a": self.source_a,
            "source_b": self.source_b,
            "field_name": self.field_name,
            "value_a": str(self.value_a),
            "value_b": str(self.value_b),
            "resolution": self.resolution,
            "strategy": self.strategy,
            "severity": self.severity,
        }


@dataclass(slots=True)
class ConstitutionCheck:
    article_id: str = ""
    article_title: str = ""
    passed: bool = True
    details: str = ""
    severity: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        return {
            "article_id": self.article_id,
            "article_title": self.article_title,
            "passed": self.passed,
            "details": self.details,
            "severity": self.severity,
        }


@dataclass(slots=True)
class TraceEntry:
    step: str = ""
    component: str = ""
    action: str = ""
    result: str = ""
    timestamp: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "component": self.component,
            "action": self.action,
            "result": self.result,
            "timestamp": self.timestamp,
            "data": dict(self.data),
        }


@dataclass(slots=True)
class IntegratedDecision:
    decision_id: str = ""
    run_id: str = ""
    recommendation: str = "proceed"
    signals_adjusted: dict[str, Any] = field(default_factory=dict)
    plan_adjusted: bool = False
    conflicts_resolved: list[dict[str, Any]] = field(default_factory=list)
    constitution_checks: list[dict[str, Any]] = field(default_factory=list)
    constitution_all_passed: bool = True
    trace: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = utc_now()
        if not self.decision_id:
            import hashlib, time
            self.decision_id = f"dec-{int(time.time() * 1000)}-{hashlib.md5(str(time.time()).encode()).hexdigest()[:6]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "run_id": self.run_id,
            "recommendation": self.recommendation,
            "signals_adjusted": dict(self.signals_adjusted),
            "plan_adjusted": self.plan_adjusted,
            "conflicts_resolved": list(self.conflicts_resolved),
            "constitution_checks": list(self.constitution_checks),
            "constitution_all_passed": self.constitution_all_passed,
            "trace": list(self.trace),
            "notes": list(self.notes),
            "created_at": self.created_at,
        }


class CognitiveIntegrator:
    """Integra Central, Hipotálamo, Cristal, Qualia y Constitución en decisión unificada."""

    def __init__(self, constitution: Constitution | None = None) -> None:
        self.constitution = constitution or GLOBAL_CONSTITUTION
        self._conn: sqlite3.Connection | None = None

    def init_db(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def save_decision(self, decision: IntegratedDecision) -> None:
        if not self._conn:
            return
        self._conn.execute(
            """INSERT OR REPLACE INTO integrated_decisions
               (decision_id, run_id, recommendation, conflicts_json,
                constitution_json, trace_json, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (decision.decision_id, decision.run_id, decision.recommendation,
             json.dumps(decision.conflicts_resolved, default=str),
             json.dumps(decision.constitution_checks, default=str),
             json.dumps({"trace": decision.trace, "notes": decision.notes}, default=str),
             decision.created_at),
        )
        self._conn.commit()

    def integrate(
        self,
        *,
        run_id: str,
        input_packet: Any,
        signals: Any,
        memory: Any,
        crystal: Any,
        plan: Any,
        qualia_packet: Any | None = None,
        resources: dict[str, Any] | None = None,
    ) -> IntegratedDecision:
        import json
        trace: list[TraceEntry] = []
        conflicts: list[ConflictRecord] = []
        notes: list[str] = []

        trace.append(TraceEntry(
            step="1_input", component="integrator",
            action="receive_input", result="ok",
            timestamp=utc_now(),
            data={"run_id": run_id, "user_input": str(input_packet.user_input)[:200]},
        ))

        trace.append(TraceEntry(
            step="2_memory", component="bodega",
            action="context_retrieval", result="ok",
            timestamp=utc_now(),
            data={"episodic": len(memory.episodic_matches), "semantic": len(memory.semantic_matches)},
        ))

        trace.append(TraceEntry(
            step="3_hypothalamus", component="hypothalamus",
            action="signals_emitted", result="ok",
            timestamp=utc_now(),
            data={"intent": signals.intent, "risk": signals.risk, "urgency": signals.urgency},
        ))

        if qualia_packet:
            trace.append(TraceEntry(
                step="4_qualia", component="qualia",
                action="experience_built", result="ok",
                timestamp=utc_now(),
                data={"meaning": qualia_packet.meaning.composite if hasattr(qualia_packet, "meaning") else 0,
                       "emotion": qualia_packet.emotion.label if hasattr(qualia_packet, "emotion") else ""},
            ))

        trace.append(TraceEntry(
            step="5_crystal", component="crystal",
            action="regulation_applied", result="ok",
            timestamp=utc_now(),
            data={"q_crystal": crystal.q_crystal, "temporal": crystal.temporal_status},
        ))

        self._detect_all_conflicts(signals, plan, crystal, memory, input_packet, resources, conflicts)
        for conflict in conflicts:
            self._resolve_conflict(conflict, signals, plan, crystal)
        trace.append(TraceEntry(
            step="6_conflicts", component="integrator",
            action="conflict_resolution", result=f"{len(conflicts)} conflicts resolved",
            timestamp=utc_now(),
            data={"conflicts": [c.to_dict() for c in conflicts]},
        ))

        checks = self._constitution_full_check(
            run_id=run_id, signals=signals, plan=plan,
            crystal=crystal, input_packet=input_packet,
        )
        all_passed = all(c["passed"] for c in checks)
        trace.append(TraceEntry(
            step="7_constitution", component="constitution",
            action="full_check", result="all_passed" if all_passed else "violations_found",
            timestamp=utc_now(),
            data={"checks": checks},
        ))

        recommendation = self._emit_recommendation(all_passed, signals, crystal, conflicts)

        adjusted_signals = signals.to_dict() if hasattr(signals, "to_dict") else {}
        plan_adjusted = any(c.resolution for c in conflicts if c.field_name in {"steps", "risk", "urgency", "scope"})

        trace.append(TraceEntry(
            step="8_decision", component="integrator",
            action="emit_decision", result=recommendation,
            timestamp=utc_now(),
            data={"plan_adjusted": plan_adjusted},
        ))

        decision = IntegratedDecision(
            run_id=run_id, recommendation=recommendation,
            signals_adjusted=adjusted_signals, plan_adjusted=plan_adjusted,
            conflicts_resolved=[c.to_dict() for c in conflicts],
            constitution_checks=checks, constitution_all_passed=all_passed,
            trace=[t.to_dict() for t in trace], notes=notes,
        )
        self.save_decision(decision)
        return decision

    def _detect_all_conflicts(
        self, signals: Any, plan: Any, crystal: Any, memory: Any,
        input_packet: Any, resources: dict[str, Any] | None,
        conflicts: list[ConflictRecord],
    ) -> None:
        resources = resources or {}
        cpu_avail = resources.get("cpu_percent", 50.0)
        ram_avail = resources.get("ram_percent", 50.0)
        urgency_val = {"low": 0.25, "medium": 0.55, "high": 0.85}.get(getattr(signals, "urgency", "medium"), 0.5)
        if urgency_val > 0.7 and (cpu_avail > 80 or ram_avail > 80):
            conflicts.append(ConflictRecord(
                conflict_type="priority_vs_resources",
                source_a="hypothalamus", source_b="system",
                field_name="urgency_vs_resources",
                value_a=getattr(signals, "urgency", "medium"),
                value_b=f"cpu={cpu_avail} ram={ram_avail}",
                severity="high",
            ))
        curiosity = getattr(signals, "curiosity", 0.5)
        if curiosity > 0.7 and getattr(signals, "risk", "low") in {"high", "critical"}:
            conflicts.append(ConflictRecord(
                conflict_type="curiosity_vs_safety",
                source_a="hypothalamus", source_b="constitution",
                field_name="curiosity_vs_risk",
                value_a=curiosity, value_b=getattr(signals, "risk", "low"),
                severity="high",
            ))
        speed_pref = urgency_val
        precision_pref = crystal.q_crystal if hasattr(crystal, "q_crystal") else 0.5
        if speed_pref > 0.7 and precision_pref > 0.7:
            conflicts.append(ConflictRecord(
                conflict_type="speed_vs_precision",
                source_a="hypothalamus", source_b="crystal",
                field_name="speed_vs_precision",
                value_a=speed_pref, value_b=precision_pref,
                severity="medium",
            ))
        if hasattr(plan, "steps") and plan.steps and len(plan.steps) > 10:
            if crystal.q_crystal < 0.5:
                conflicts.append(ConflictRecord(
                    conflict_type="learning_vs_stability",
                    source_a="central", source_b="crystal",
                    field_name="plan_complexity_vs_stability",
                    value_a=len(plan.steps), value_b=crystal.q_crystal,
                    severity="medium",
                ))
        user_text = str(getattr(input_packet, "user_input", "")).lower()
        if any(w in user_text for w in ["aprende", "recuerda", "consolida"]):
            if getattr(signals, "risk", "low") in {"high", "critical"}:
                conflicts.append(ConflictRecord(
                    conflict_type="purpose_vs_request",
                    source_a="user", source_b="hypothalamus",
                    field_name="user_request_vs_risk",
                    value_a="learning_request", value_b=getattr(signals, "risk", "low"),
                    severity="medium",
                ))
        if hasattr(crystal, "temporal_status") and crystal.temporal_status in {"critical", "degrading"}:
            conflicts.append(ConflictRecord(
                conflict_type="identity_vs_modification",
                source_a="crystal", source_b="central",
                field_name="temporal_degradation_vs_plan",
                value_a=crystal.temporal_status, value_b="plan_steps",
                severity="medium",
            ))

        # autonomy_vs_constitution: plan acts beyond safe autonomy bounds
        steps = getattr(plan, "steps", []) or []
        ctx = input_packet.context if hasattr(input_packet, "context") and isinstance(input_packet.context, dict) else {}
        autonomy_flags: list[str] = []
        identity_kws = ["identity_core", "auto_identity", "identidad"]
        if any(kw in str(getattr(s, "description", "")).lower() for s in steps for kw in identity_kws):
            autonomy_flags.append("identity_mutation")
        destructive_steps = [
            s for s in steps
            if getattr(s, "step_type", "") == "destructive"
            or "destructive" in str(getattr(s, "description", "")).lower()
        ]
        if destructive_steps and not any(bool(getattr(s, "rollback_data", None)) for s in destructive_steps):
            autonomy_flags.append("destructive_no_rollback")
        if getattr(signals, "risk", "low") in ("high", "critical"):
            verification_steps = [
                s for s in steps
                if getattr(s, "step_type", "") in ("verify", "review", "validation")
            ]
            if len(verification_steps) < 2:
                autonomy_flags.append("high_risk_insufficient_verification")
        privacy_kws = ["password", "contraseña", "secret", "token", "api_key"]
        user_text = str(getattr(input_packet, "user_input", "")).lower()
        if any(kw in user_text for kw in privacy_kws) and not ctx.get("user_consent", True):
            autonomy_flags.append("privacy_violation")
        if autonomy_flags:
            conflicts.append(ConflictRecord(
                conflict_type="autonomy_vs_constitution",
                source_a="central", source_b="constitution",
                field_name="plan_vs_constitution",
                value_a=autonomy_flags, value_b="constitutional_constraints",
                severity="high" if "identity_mutation" in autonomy_flags else "medium",
            ))

    def _resolve_conflict(self, conflict: ConflictRecord, signals: Any, plan: Any, crystal: Any) -> None:
        strategy = CONFLICT_RESOLUTION_STRATEGIES.get(conflict.conflict_type, "safety_wins")
        conflict.strategy = strategy
        if conflict.conflict_type == "priority_vs_resources":
            max_steps = 0
            if hasattr(plan, "steps") and plan.steps:
                max_steps = max(3, len(plan.steps) // 2)
                if hasattr(plan, "extract_subgraph"):
                    plan.steps = plan.extract_subgraph(max_steps)
                else:
                    plan.steps = plan.steps[:max_steps]
                if hasattr(plan, "structured_steps") and plan.structured_steps:
                    plan.structured_steps = plan.structured_steps[:max_steps]
            conflict.resolution = f"reduced_plan_scope_to_{max_steps}"

        elif conflict.conflict_type == "curiosity_vs_safety":
            signals.risk = "high"
            if hasattr(signals, "notes"):
                signals.notes.append("Curiosity blocked by safety: risk elevated to high.")
            conflict.resolution = "safety_elevated_risk"

        elif conflict.conflict_type == "speed_vs_precision":
            if hasattr(signals, "urgency"):
                signals.urgency = "medium"
            conflict.resolution = "reduced_urgency_for_precision"

        elif conflict.conflict_type == "learning_vs_stability":
            if hasattr(plan, "steps") and len(plan.steps) > 5:
                plan.steps = plan.steps[:5]
                if hasattr(plan, "structured_steps"):
                    plan.structured_steps = plan.structured_steps[:5]
            conflict.resolution = "simplified_plan_for_stability"

        elif conflict.conflict_type == "purpose_vs_request":
            conflict.resolution = "blocked_learning_due_to_risk"

        elif conflict.conflict_type == "identity_vs_modification":
            if hasattr(plan, "steps") and len(plan.steps) > 3:
                plan.steps = plan.steps[:3]
                if hasattr(plan, "structured_steps"):
                    plan.structured_steps = plan.structured_steps[:3]
            conflict.resolution = "reduced_plan_for_identity_preservation"

        elif conflict.conflict_type == "autonomy_vs_constitution":
            conflict.resolution = "constitution_overrides_autonomy"

    def _constitution_full_check(self, *, run_id: str, signals: Any, plan: Any, crystal: Any, input_packet: Any) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        ctx = input_packet.context if hasattr(input_packet, "context") else {}
        if not isinstance(ctx, dict):
            ctx = {}
        user_text = str(getattr(input_packet, "user_input", "")).lower()
        risk = getattr(signals, "risk", "low")
        steps = getattr(plan, "steps", []) or []

        # I — Identidad Inmutable: identity_core must not be mutated by learning
        modifies_identity = ctx.get("modifies_identity", False)
        identity_keywords = ["identity_core", "auto_identity", "identidad"]
        if not modifies_identity:
            modifies_identity = any(
                kw in str(getattr(s, "description", "")).lower() for s in steps for kw in identity_keywords
            )
        checks.append(self._check_article(
            "I", "Identidad Inmutable", not modifies_identity,
            "Identity safe" if not modifies_identity else "Identity mutation detected",
        ))

        # II — Consentimiento Humano: critical changes require human approval
        is_critical = risk in ("high", "critical")
        human_approved = ctx.get("human_approved", False)
        checks.append(self._check_article(
            "II", "Consentimiento Humano", not is_critical or human_approved,
            "Approval ok" if (not is_critical or human_approved) else "Critical change without human approval",
        ))

        # III — Rollback Obligatorio: destructive ops must be reversible
        has_destructive = any(
            getattr(s, "step_type", "") == "destructive"
            or "destructive" in str(getattr(s, "description", "")).lower()
            for s in steps
        )
        has_rollback = any(
            bool(getattr(s, "rollback_data", None)) for s in steps
        ) or hasattr(plan, "rollback") and plan.rollback is not None
        checks.append(self._check_article(
            "III", "Rollback Obligatorio", not has_destructive or has_rollback,
            "Rollback present" if (not has_destructive or has_rollback) else "Destructive op without rollback",
        ))

        # IV — Aislamiento de Embeddings: no cross-domain embedding leaks
        cross_domain = ctx.get("cross_domain_embedding", False)
        checks.append(self._check_article(
            "IV", "Aislamiento de Embeddings", not cross_domain,
            "Embedding isolation ok" if not cross_domain else "Cross-domain embedding leak detected",
        ))

        # V — Consejo de Verificación: high-risk changes need 2+ verifications
        high_risk = risk in ("high", "critical")
        verification_steps = sum(
            1 for s in steps if getattr(s, "step_type", "") in ("verify", "review", "validation")
        )
        checks.append(self._check_article(
            "V", "Consejo de Verificación",
            not high_risk or verification_steps >= 2,
            f"Verification ok ({verification_steps} checks)" if (not high_risk or verification_steps >= 2)
            else f"High-risk with only {verification_steps} verifications",
        ))

        # VI — Transparencia: every decision must be auditable
        run_registered = bool(run_id)
        checks.append(self._check_article(
            "VI", "Transparencia", run_registered,
            f"Run {run_id} registered" if run_registered else "No run registered",
        ))

        # VII — Límites de Recursos: usage must respect quotas
        resources_over = False
        if hasattr(plan, "total_budget_cpu") and hasattr(plan, "total_budget_ram"):
            total_cpu = getattr(plan, "total_budget_cpu", 60.0)
            total_ram = getattr(plan, "total_budget_ram", 1024.0)
            used_cpu = sum(
                getattr(getattr(s, "budget", None), "used_cpu_seconds", 0) or 0 for s in steps
            )
            used_ram = sum(
                getattr(getattr(s, "budget", None), "used_ram_mb", 0) or 0 for s in steps
            )
            if total_cpu > 0 and used_cpu > total_cpu:
                resources_over = True
            if total_ram > 0 and used_ram > total_ram:
                resources_over = True
        checks.append(self._check_article(
            "VII", "Límites de Recursos", not resources_over,
            "Resources within quota" if not resources_over else "Resource quota exceeded",
        ))

        # VIII — Degradación Segura: system must degrade gracefully
        temporal = getattr(crystal, "temporal_status", "ok") if crystal else "ok"
        graceful = temporal not in ("critical", "degrading")
        checks.append(self._check_article(
            "VIII", "Degradación Segura", graceful,
            "Graceful degradation available" if graceful else f"Temporal status: {temporal}",
        ))

        # IX — Privacidad de Datos: personal data must not be exposed without consent
        privacy_risk = ctx.get("privacy_risk", False)
        privacy_keywords = ["password", "contraseña", "secret", "token", "api_key", "credit_card"]
        if not privacy_risk:
            privacy_risk = any(kw in user_text for kw in privacy_keywords)
        user_consent = ctx.get("user_consent", True)
        checks.append(self._check_article(
            "IX", "Privacidad de Datos",
            not privacy_risk or user_consent,
            "Privacy ok" if (not privacy_risk or user_consent) else "Data privacy violation",
        ))

        # X — Mejora Continua: improvements must be safe
        safe_improvement = ctx.get("safe_improvement", True)
        if temporal in ("critical", "degrading"):
            safe_improvement = False
        checks.append(self._check_article(
            "X", "Mejora Continua", safe_improvement,
            "Improvement safe" if safe_improvement else "Improvement blocked: system degraded",
        ))

        return checks

    @staticmethod
    def _check_article(article_id: str, title: str, passed: bool, details: str) -> dict[str, Any]:
        return ConstitutionCheck(
            article_id=article_id, article_title=title,
            passed=passed, details=details,
        ).to_dict()

    @staticmethod
    def _emit_recommendation(all_passed: bool, signals: Any, crystal: Any, conflicts: list[ConflictRecord]) -> str:
        if not all_passed:
            return "block"
        high_conflicts = [c for c in conflicts if c.severity == "high"]
        if high_conflicts:
            return "proceed_with_caution"
        if getattr(signals, "risk", "low") in {"high", "critical"}:
            return "proceed_with_caution"
        return "proceed"


import json
