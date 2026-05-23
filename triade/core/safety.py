"""Safety · evaluación preventiva regulada por Crystal y memoria gobernada."""

from __future__ import annotations

from .contracts import CrystalPacket, MemoryPacket, PlanPacket, SafetyPacket, SignalPacket


class Safety:
    """Evalúa riesgo de entrada, plan, Cristal y memoria semántica.

    Desde 1.9E, una memoria vectorial candidata, rechazada o experimental no
    autorizada queda en cuarentena y produce evidencia preventiva sin bloquear
    por sí sola una conversación.
    """

    def review(
        self,
        signals: SignalPacket,
        plan: PlanPacket,
        crystal: CrystalPacket | None = None,
        memory: MemoryPacket | None = None,
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

        if memory is not None:
            governance = memory.semantic_recall.get("governance", {})
            quarantined = int(governance.get("quarantined_vector_matches", 0) or 0)
            allowed = int(governance.get("allowed_vector_matches", 0) or 0)
            if quarantined > 0:
                risk_types.append("semantic_memory_unverified")
                controls.append("No usar memorias semánticas en cuarentena como hechos consolidados.")
                reason_parts.append(
                    f"Gobierno semántico aisló {quarantined} recuerdo(s) no autorizado(s) para influencia."
                )
                risk_level = self._raise_risk_level(risk_level, "medium")
                if status == "approved":
                    status = "approved_with_warning"
            if allowed > 0:
                controls.append("Atribuir memoria semántica autorizada usando su fuente y estado persistido.")

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
            risk_types=list(dict.fromkeys(risk_types)),
            reason=reason,
            required_controls=list(dict.fromkeys(controls)),
            human_approval_required=human_approval,
        )

    @staticmethod
    def _raise_risk_level(current: str, minimum: str) -> str:
        rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        return current if rank.get(current, 0) >= rank.get(minimum, 0) else minimum
