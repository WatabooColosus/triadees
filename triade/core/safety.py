"""Safety · evaluación preventiva regulada por Crystal."""

from __future__ import annotations

from .contracts import CrystalPacket, PlanPacket, SafetyPacket, SignalPacket


class Safety:
    """Evalúa riesgo de entrada, plan y continuidad temporal del Cristal.

    Fase 1.8E: una degradación temporal no bloquea por sí sola una conversación,
    pero eleva advertencias; si el plan contiene herramientas o modificaciones,
    requiere autorización humana antes de ejecutar.
    """

    def review(
        self,
        signals: SignalPacket,
        plan: PlanPacket,
        crystal: CrystalPacket | None = None,
    ) -> SafetyPacket:
        risk_types: list[str] = []
        controls: list[str] = []
        status = "approved"
        reason_parts: list[str] = []
        human_approval = False
        risk_level = signals.risk

        if signals.risk in {"high", "critical"}:
            status = "requires_human_approval"
            risk_types.append("operational")
            controls.append("Solicitar confirmación humana antes de ejecutar.")
            reason_parts.append("Se detectó riesgo alto en la entrada o plan.")
            human_approval = True
        elif plan.tools:
            status = "approved_with_warning"
            risk_types.append("operational")
            controls.append("Registrar acción y evitar cambios destructivos.")
            reason_parts.append("El plan puede implicar actualización de archivos o repositorio.")

        if crystal is not None and crystal.temporal_status in {"degrading", "critical"}:
            if "cognitive_temporal" not in risk_types:
                risk_types.append("cognitive_temporal")
            controls.append("Registrar alerta del Cristal y revisar tendencia antes de consolidar cambios.")
            reason_parts.append(
                f"Cristal en estado temporal {crystal.temporal_status}: "
                f"ΔQ={crystal.q_delta}, Δestabilidad={crystal.stability_delta}."
            )
            risk_level = self._raise_risk_level(risk_level, "high" if crystal.temporal_status == "critical" else "medium")

            if plan.tools:
                status = "requires_human_approval"
                human_approval = True
                controls.append("Requerir aprobación humana para acciones con herramientas durante degradación temporal.")
            elif status == "approved":
                status = "approved_with_warning"

        reason = " ".join(reason_parts) if reason_parts else "Sin riesgo elevado detectado por reglas MVP."

        return SafetyPacket(
            run_id=signals.run_id,
            status=status,  # type: ignore[arg-type]
            risk_level=risk_level,  # type: ignore[arg-type]
            risk_types=risk_types,
            reason=reason,
            required_controls=list(dict.fromkeys(controls)),
            human_approval_required=human_approval,
        )

    @staticmethod
    def _raise_risk_level(current: str, minimum: str) -> str:
        rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        return current if rank.get(current, 0) >= rank.get(minimum, 0) else minimum
