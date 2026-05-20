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
        usefulness_score = 0.70

        if safety.status in {"approved_with_warning", "requires_human_approval"}:
            warnings.append(safety.reason)
            safety_score = 0.65

        if safety.status == "blocked":
            errors.append("Safety bloqueó la ejecución.")
            status = "blocked"
            safety_score = 0.2

        memory_stored = bool(output.memory_diff.get("stored"))

        # Nota: verification_report_id todavía no existe en este punto, porque
        # el VerificationReport se guarda después de ejecutar este verificador.
        # Por eso la persistencia completa verificable aquí se mide con los
        # paquetes previos: episodio, señal, cristal y safety.
        full_pre_report_persistence = memory_stored and all(
            output.memory_diff.get(key) is not None
            for key in ["episode_id", "signal_id", "crystal_id", "safety_id"]
        )

        if memory_stored:
            memory_score = 0.80
            traceability_score = 0.90
        else:
            warnings.append("El episodio no fue persistido en memoria SQLite.")
            recommendations.append("Revisar Bodega.store_episode y la ruta de triade.db.")

        if full_pre_report_persistence:
            memory_score = 0.90
            traceability_score = 0.95
        else:
            recommendations.extend(
                [
                    "Completar persistencia previa al reporte: episodio, señal, cristal y safety.",
                    "Ejecutar python triade_digimon.py doctor para verificar conteos de persistencia.",
                ]
            )

        hypothalamus_ok = bool(output.memory_diff.get("hypothalamus_model_ok"))
        central_ok = bool(output.memory_diff.get("central_model_ok"))
        central_requested_ollama = output.model_provider == "ollama"

        if hypothalamus_ok and central_ok:
            usefulness_score = 0.85
            recommendations.extend(
                [
                    "Agregar selección de modelo por CLI para Hipotálamo y Central.",
                    "Crear métricas de calidad de señales y respuesta por rol.",
                    "Crear tabla dedicada para eventos de modelo por run.",
                ]
            )
        elif central_requested_ollama and output.model_ok and not hypothalamus_ok:
            usefulness_score = 0.80
            recommendations.extend(
                [
                    "Revisar por qué el Hipotálamo usó fallback y mejorar su prompt JSON.",
                    "Ejecutar python triade_digimon.py doctor para revisar estado de Ollama.",
                ]
            )
        elif central_requested_ollama and not output.model_ok:
            warnings.append("Ollama fue solicitado pero no generó respuesta central; se usó fallback por plantilla.")
            recommendations.extend(
                [
                    "Verificar que Ollama esté corriendo en http://127.0.0.1:11434.",
                    "Ejecutar ollama list y confirmar que el modelo configurado existe.",
                ]
            )
        else:
            recommendations.extend(
                [
                    "Ejecutar sin --no-ollama para validar respuesta con modelo local.",
                    "Usar python triade_digimon.py doctor para revisar estado de Ollama.",
                ]
            )

        return VerificationReport(
            run_id=output.run_id,
            status=status,
            coherence_score=0.75,
            memory_score=memory_score,
            safety_score=safety_score,
            usefulness_score=usefulness_score,
            traceability_score=traceability_score,
            errors=errors,
            warnings=warnings,
            recommendations=recommendations,
        )
