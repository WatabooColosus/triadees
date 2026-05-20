"""Verificación · MVP."""

from __future__ import annotations

from .contracts import OutputPacket, SafetyPacket, VerificationReport


class Verifier:
    """Genera un reporte simple de calidad e integridad."""

    def verify(self, output: OutputPacket, safety: SafetyPacket) -> VerificationReport:
        warnings: list[str] = []
        errors: list[str] = []
        recommendations: list[str] = []

        status = output.status
        safety_score = 0.9
        memory_score = 0.55
        traceability_score = 0.80

        if safety.status in {"approved_with_warning", "requires_human_approval"}:
            warnings.append(safety.reason)
            safety_score = 0.65

        if safety.status == "blocked":
            errors.append("Safety bloqueó la ejecución.")
            status = "blocked"
            safety_score = 0.2

        memory_stored = bool(output.memory_diff.get("stored"))
        full_persistence = all(
            output.memory_diff.get(key) is not None
            for key in ["signal_id", "crystal_id", "safety_id", "verification_report_id"]
        )

        if memory_stored:
            memory_score = 0.80
            traceability_score = 0.90
        else:
            warnings.append("El episodio no fue persistido en memoria SQLite.")
            recommendations.append("Revisar Bodega.store_episode y la ruta de triade.db.")

        if full_persistence:
            memory_score = 0.90
            traceability_score = 0.95
            recommendations.extend(
                [
                    "Conectar adaptador Ollama para respuestas generadas por modelo local.",
                    "Agregar configuración de modelos por rol: Hipotálamo y Central.",
                    "Registrar el modelo usado en cada run dentro de SQLite.",
                ]
            )
        else:
            recommendations.extend(
                [
                    "Completar persistencia de SignalPacket, CrystalPacket, SafetyPacket y VerificationReport.",
                    "Ejecutar python triade_digimon.py doctor para verificar conteos de persistencia.",
                ]
            )

        return VerificationReport(
            run_id=output.run_id,
            status=status,
            coherence_score=0.75,
            memory_score=memory_score,
            safety_score=safety_score,
            usefulness_score=0.70,
            traceability_score=traceability_score,
            errors=errors,
            warnings=warnings,
            recommendations=recommendations,
        )
