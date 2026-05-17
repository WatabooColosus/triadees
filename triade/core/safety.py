"""Safety · MVP."""

from __future__ import annotations

from .contracts import PlanPacket, SafetyPacket, SignalPacket


class Safety:
    """Evaluación mínima de riesgo antes de salida o acción."""

    def review(self, signals: SignalPacket, plan: PlanPacket) -> SafetyPacket:
        risk_types: list[str] = []
        controls: list[str] = []
        status = "approved"
        reason = "Sin riesgo elevado detectado por reglas MVP."
        human_approval = False

        if signals.risk in {"high", "critical"}:
            status = "requires_human_approval"
            risk_types.append("operational")
            controls.append("Solicitar confirmación humana antes de ejecutar.")
            reason = "Se detectó riesgo alto en la entrada o plan."
            human_approval = True
        elif plan.tools:
            status = "approved_with_warning"
            risk_types.append("operational")
            controls.append("Registrar acción y evitar cambios destructivos.")
            reason = "El plan puede implicar actualización de archivos o repositorio."

        return SafetyPacket(
            run_id=signals.run_id,
            status=status,  # type: ignore[arg-type]
            risk_level=signals.risk,
            risk_types=risk_types,
            reason=reason,
            required_controls=controls,
            human_approval_required=human_approval,
        )
