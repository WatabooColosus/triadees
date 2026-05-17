"""Verificación · MVP."""

from __future__ import annotations

from .contracts import OutputPacket, SafetyPacket, VerificationReport


class Verifier:
    """Genera un reporte simple de calidad e integridad."""

    def verify(self, output: OutputPacket, safety: SafetyPacket) -> VerificationReport:
        warnings: list[str] = []
        errors: list[str] = []

        status = output.status
        safety_score = 0.9

        if safety.status in {"approved_with_warning", "requires_human_approval"}:
            warnings.append(safety.reason)
            safety_score = 0.65

        if safety.status == "blocked":
            errors.append("Safety bloqueó la ejecución.")
            status = "blocked"
            safety_score = 0.2

        return VerificationReport(
            run_id=output.run_id,
            status=status,
            coherence_score=0.75,
            memory_score=0.55,
            safety_score=safety_score,
            usefulness_score=0.70,
            traceability_score=0.80,
            errors=errors,
            warnings=warnings,
            recommendations=[
                "Conectar persistencia SQLite en Bodega.",
                "Agregar tests automatizados del ciclo cognitivo.",
            ],
        )
