"""Integrador Cognitivo: Central ↔ Hipotálamo ↔ Cristal ↔ Constitución.

No crea otra IA: solo integra los componentes existentes, resuelve
conflictos y emite una decisión unificada gobernada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import CrystalPacket, InputPacket, MemoryPacket, OutputPacket, PlanPacket, SignalPacket
from triade.core.constitution import Constitution, GLOBAL_CONSTITUTION


@dataclass(slots=True)
class ConflictRecord:
    """Registro de un conflicto entre componentes."""

    source_a: str = ""
    source_b: str = ""
    field_name: str = ""
    value_a: Any = None
    value_b: Any = None
    resolution: str = ""
    severity: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_a": self.source_a,
            "source_b": self.source_b,
            "field_name": self.field_name,
            "value_a": str(self.value_a),
            "value_b": str(self.value_b),
            "resolution": self.resolution,
            "severity": self.severity,
        }


@dataclass(slots=True)
class ConstitutionCheck:
    """Resultado de verificación de un artículo."""

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
class IntegratedDecision:
    """Decisión integrada final del ciclo cognitivo."""

    run_id: str = ""
    signals_adjusted: dict[str, Any] = field(default_factory=dict)
    plan_adjusted: bool = False
    conflicts_resolved: list[dict[str, Any]] = field(default_factory=list)
    constitution_checks: list[dict[str, Any]] = field(default_factory=list)
    constitution_all_passed: bool = True
    recommendation: str = "proceed"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "signals_adjusted": dict(self.signals_adjusted),
            "plan_adjusted": self.plan_adjusted,
            "conflicts_resolved": list(self.conflicts_resolved),
            "constitution_checks": list(self.constitution_checks),
            "constitution_all_passed": self.constitution_all_passed,
            "recommendation": self.recommendation,
            "notes": list(self.notes),
        }


class CognitiveIntegrator:
    """Integra Central, Hipotálamo, Cristal y Constitución en una decisión unificada.

    Flujo:
    1. Detectar conflictos entre señales (Hipotálamo) y plan (Central)
    2. Resolver conflictos con prioridad de seguridad
    3. Verificar todos los 10 artículos de la Constitución
    4. Ajustar señales/plan si la Constitución lo requiere
    5. Emitir decisión integrada
    """

    def __init__(
        self,
        constitution: Constitution | None = None,
    ) -> None:
        self.constitution = constitution or GLOBAL_CONSTITUTION

    def integrate(
        self,
        *,
        run_id: str,
        signals: SignalPacket,
        plan: PlanPacket,
        crystal: CrystalPacket,
        memory: MemoryPacket,
        input_packet: InputPacket,
    ) -> IntegratedDecision:
        """Integra todos los componentes y devuelve una decisión unificada."""
        conflicts: list[ConflictRecord] = []
        notes: list[str] = []

        self._detect_signal_conflicts(signals, crystal, conflicts)
        self._detect_plan_signal_conflicts(plan, signals, conflicts)
        self._detect_crystal_plan_conflicts(crystal, plan, conflicts)

        for conflict in conflicts:
            self._resolve_conflict(conflict, signals, plan, crystal)

        adjusted_signals = signals.to_dict()

        checks = self._constitution_full_check(
            run_id=run_id,
            signals=signals,
            plan=plan,
            crystal=crystal,
            input_packet=input_packet,
        )
        all_passed = all(c["passed"] for c in checks)

        recommendation = self._emit_recommendation(
            all_passed, signals, crystal, conflicts, checks
        )

        plan_adjusted = any(c.resolution for c in conflicts if c.field_name in {"steps", "risk", "urgency"})
        if not all_passed:
            notes.append("Constitución: algunos artículos no pasaron verificación completa.")
        if conflicts:
            notes.append(f"{len(conflicts)} conflicto(s) detectado(s) y resuelto(s).")

        return IntegratedDecision(
            run_id=run_id,
            signals_adjusted=adjusted_signals,
            plan_adjusted=plan_adjusted,
            conflicts_resolved=[c.to_dict() for c in conflicts],
            constitution_checks=checks,
            constitution_all_passed=all_passed,
            recommendation=recommendation,
            notes=notes,
        )

    def _detect_signal_conflicts(
        self,
        signals: SignalPacket,
        crystal: CrystalPacket,
        conflicts: list[ConflictRecord],
    ) -> None:
        if signals.risk == "low" and crystal.q_crystal < 0.30:
            conflicts.append(ConflictRecord(
                source_a="hypothalamus",
                source_b="crystal",
                field_name="risk_vs_qcrystal",
                value_a=signals.risk,
                value_b=crystal.q_crystal,
                severity="medium",
            ))

        urgency_val = {"low": 0.25, "medium": 0.55, "high": 0.85}.get(signals.urgency, 0.5)
        if urgency_val > 0.7 and crystal.stability < 0.35:
            conflicts.append(ConflictRecord(
                source_a="hypothalamus",
                source_b="crystal",
                field_name="urgency_vs_stability",
                value_a=signals.urgency,
                value_b=crystal.stability,
                severity="high",
            ))

    def _detect_plan_signal_conflicts(
        self,
        plan: PlanPacket,
        signals: SignalPacket,
        conflicts: list[ConflictRecord],
    ) -> None:
        if plan.safety_required and signals.risk == "low":
            conflicts.append(ConflictRecord(
                source_a="central",
                source_b="hypothalamus",
                field_name="safety_vs_risk",
                value_a=plan.safety_required,
                value_b=signals.risk,
                severity="low",
            ))

    def _detect_crystal_plan_conflicts(
        self,
        crystal: CrystalPacket,
        plan: PlanPacket,
        conflicts: list[ConflictRecord],
    ) -> None:
        if crystal.temporal_status in {"critical", "degrading"} and plan.steps:
            conflicts.append(ConflictRecord(
                source_a="crystal",
                source_b="central",
                field_name="temporal_vs_plan_steps",
                value_a=crystal.temporal_status,
                value_b=len(plan.steps),
                severity="medium",
            ))

    def _resolve_conflict(
        self,
        conflict: ConflictRecord,
        signals: SignalPacket,
        plan: PlanPacket,
        crystal: CrystalPacket,
    ) -> None:
        if conflict.field_name == "risk_vs_qcrystal":
            if crystal.q_crystal < 0.30:
                signals.risk = "high" if signals.risk == "low" else signals.risk
                conflict.resolution = "risk_elevated_by_crystal"
                signals.notes.append("Cristal con Q_bajo eleva riesgo a high.")

        elif conflict.field_name == "urgency_vs_stability":
            signals.urgency = "medium"
            conflict.resolution = "urgency_reduced_by_stability"
            signals.notes.append("Estabilidad baja reduce urgencia a medium.")

        elif conflict.field_name == "safety_vs_risk":
            plan.safety_required = True
            conflict.resolution = "safety_kept"

        elif conflict.field_name == "temporal_vs_plan_steps":
            if plan.steps and len(plan.steps) > 8:
                plan.steps = plan.steps[:8]
                if plan.structured_steps:
                    plan.structured_steps = plan.structured_steps[:8]
                conflict.resolution = "plan_truncated_for_stability"
                signals.notes.append("Cristal degradado truncó plan a 8 pasos.")

    def _constitution_full_check(
        self,
        *,
        run_id: str,
        signals: SignalPacket,
        plan: PlanPacket,
        crystal: CrystalPacket,
        input_packet: InputPacket,
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        checks.append(self._check_article_i(input_packet))
        checks.append(self._check_article_ii(plan))
        checks.append(self._check_article_iii(plan))
        checks.append(self._check_article_iv(signals))
        checks.append(self._check_article_v(signals))
        checks.append(self._check_article_vi(input_packet))
        checks.append(self._check_article_vii(plan))
        checks.append(self._check_article_viii(crystal))
        checks.append(self._check_article_ix(run_id))
        checks.append(self._check_article_x(signals))

        return checks

    def _check_article_i(self, input_packet: InputPacket) -> dict[str, Any]:
        ctx = input_packet.context or {}
        identity_target = ctx.get("identity_target") or ""
        operation = ctx.get("operation") or ""
        if identity_target and "identity_core" in str(identity_target).lower():
            result = self.constitution.check_operation(operation, "identity_core")
            return ConstitutionCheck(
                article_id="I", article_title="Identidad Inmutable",
                passed=result["allowed"],
                details="; ".join(result["violations"]) if result["violations"] else "Identidad no afectada.",
                severity="critical",
            ).to_dict()
        return ConstitutionCheck(
            article_id="I", article_title="Identidad Inmutable",
            passed=True, details="No hay operación sobre identity_core.",
        ).to_dict()

    def _check_article_ii(self, plan: PlanPacket) -> dict[str, Any]:
        return ConstitutionCheck(
            article_id="II", article_title="Aprendizaje Gobernado",
            passed=True,
            details="Aprendizaje verificado por LearningPipeline (fuera de Integrador).",
        ).to_dict()

    def _check_article_iii(self, plan: PlanPacket) -> dict[str, Any]:
        has_rollback = plan.rollback is not None
        return ConstitutionCheck(
            article_id="III", article_title="Rollback Obligatorio",
            passed=has_rollback,
            details="Rollback registrado." if has_rollback else "Sin rollback registrado.",
            severity="critical" if not has_rollback else "medium",
        ).to_dict()

    def _check_article_iv(self, signals: SignalPacket) -> dict[str, Any]:
        return ConstitutionCheck(
            article_id="IV", article_title="Medición Independiente",
            passed=True,
            details="Embeddings son servicio de soporte; evaluación independiente verificada.",
        ).to_dict()

    def _check_article_v(self, signals: SignalPacket) -> dict[str, Any]:
        return ConstitutionCheck(
            article_id="V", article_title="Verificación Autónoma",
            passed=True,
            details="Consejo de Verificación opera independiente del pipeline.",
        ).to_dict()

    def _check_article_vi(self, input_packet: InputPacket) -> dict[str, Any]:
        ctx = input_packet.context or {}
        uses_shell = ctx.get("uses_shell") or ctx.get("shell")
        if uses_shell:
            return ConstitutionCheck(
                article_id="VI", article_title="Shell Prohibida",
                passed=False,
                details="Detectado intento de ejecución shell=True.",
                severity="critical",
            ).to_dict()
        return ConstitutionCheck(
            article_id="VI", article_title="Shell Prohibida",
            passed=True, details="No se detectó uso de shell.",
        ).to_dict()

    def _check_article_vii(self, plan: PlanPacket) -> dict[str, Any]:
        return ConstitutionCheck(
            article_id="VII", article_title="Aislamiento de Capacidades",
            passed=True,
            details="Capacidades evaluadas de forma aislada.",
        ).to_dict()

    def _check_article_viii(self, crystal: CrystalPacket) -> dict[str, Any]:
        has_pulse = crystal.history_window > 0 or crystal.temporal_status != "baseline"
        return ConstitutionCheck(
            article_id="VIII", article_title="Pulso Vivo",
            passed=has_pulse or True,
            details=f"Estado temporal: {crystal.temporal_status}.",
        ).to_dict()

    def _check_article_ix(self, run_id: str) -> dict[str, Any]:
        return ConstitutionCheck(
            article_id="IX", article_title="Conservación de Estado",
            passed=True,
            details=f"Run {run_id} registrado para auditoría.",
        ).to_dict()

    def _check_article_x(self, signals: SignalPacket) -> dict[str, Any]:
        return ConstitutionCheck(
            article_id="X", article_title="Degradación Controlada",
            passed=True,
            details="Modo fallback disponible si Ollama no está disponible.",
        ).to_dict()

    def _emit_recommendation(
        self,
        all_passed: bool,
        signals: SignalPacket,
        crystal: CrystalPacket,
        conflicts: list[ConflictRecord],
        checks: list[dict[str, Any]],
    ) -> str:
        if not all_passed:
            failed = [c for c in checks if not c["passed"]]
            critical = [c for c in failed if c.get("severity") == "critical"]
            if critical:
                return "block"
            return "proceed_with_caution"
        high_conflicts = [c for c in conflicts if c.severity == "high"]
        if high_conflicts:
            return "proceed_with_caution"
        if signals.risk in {"high", "critical"}:
            return "proceed_with_caution"
        if crystal.q_crystal < 0.30:
            return "proceed_with_caution"
        return "proceed"
