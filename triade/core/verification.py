"""Verificación · calidad, trazabilidad y retroalimentación del Cristal y memoria."""

from __future__ import annotations

from .contracts import CrystalPacket, MemoryPacket, OutputPacket, SafetyPacket, VerificationReport


class Verifier:
    """Genera reporte verificable e incorpora continuidad y gobierno semántico."""

    def verify(
        self,
        output: OutputPacket,
        safety: SafetyPacket,
        crystal: CrystalPacket | None = None,
        memory: MemoryPacket | None = None,
    ) -> VerificationReport:
        warnings: list[str] = []
        errors: list[str] = []
        recommendations: list[str] = []

        status = output.status
        coherence_score = 0.75
        safety_score = 0.90
        memory_score = 0.55
        traceability_score = 0.80
        usefulness_score = 0.70

        if safety.status in {"approved_with_warning", "approved"} and safety.risk_level in {"high", "critical"}:
            warnings.append(safety.reason)
            safety_score = 0.65

        if safety.status == "blocked":
            errors.append("Safety bloqueó la ejecución.")
            status = "blocked"
            safety_score = 0.20

        memory_stored = bool(output.memory_diff.get("stored"))
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

        if memory is not None:
            governance = memory.semantic_recall.get("governance", {})
            quarantined = int(governance.get("quarantined_vector_matches", 0) or 0)
            allowed = int(governance.get("allowed_vector_matches", 0) or 0)
            if quarantined > 0:
                warnings.append(
                    f"Gobierno semántico dejó en cuarentena {quarantined} recuerdo(s) recuperado(s) no autorizado(s)."
                )
                recommendations.append(
                    "Promover memorias verificadas mediante transición auditable antes de permitir su influencia en Central."
                )
                memory_score = min(memory_score, 0.75)
                if status == "ok":
                    status = "warning"
            if allowed > 0:
                recommendations.append(
                    "Mantener atribución literal de document_id, source_ref y document_status para memoria semántica autorizada."
                )

        if crystal is not None:
            temporal_status = crystal.temporal_status
            if temporal_status == "degrading":
                warnings.append(
                    f"Cristal detectó degradación temporal: ΔQ={crystal.q_delta}, "
                    f"Δestabilidad={crystal.stability_delta}."
                )
                coherence_score = min(coherence_score, 0.60)
                safety_score = min(safety_score, 0.65)
                recommendations.append(
                    "Revisar la causa de degradación temporal antes de consolidar cambios estructurales."
                )
                if status == "ok":
                    status = "warning"
            elif temporal_status == "critical":
                warnings.append(
                    f"Cristal en estado temporal crítico: Q={crystal.q_crystal}, "
                    f"estabilidad={crystal.stability}."
                )
                coherence_score = min(coherence_score, 0.35)
                safety_score = min(safety_score, 0.40)
                recommendations.append(
                    "Suspender acciones expansivas y exigir revisión humana antes de cambios sensibles."
                )
                if status == "ok":
                    status = "warning"
            elif temporal_status == "improving":
                recommendations.append("Mantener trazabilidad mientras continúa la mejora temporal del Cristal.")

        hypothalamus_ok = bool(output.memory_diff.get("hypothalamus_model_ok"))
        central_ok = bool(output.memory_diff.get("central_model_ok"))
        central_requested_ollama = output.model_provider == "ollama"

        if hypothalamus_ok and central_ok:
            usefulness_score = 0.85
            recommendations.append("Continuar registrando métricas de calidad por rol de modelo.")
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
                    "Ejecutar con Ollama activo para validar respuesta con modelo local.",
                    "Usar python triade_digimon.py doctor para revisar estado de Ollama.",
                ]
            )

        return VerificationReport(
            run_id=output.run_id,
            status=status,  # type: ignore[arg-type]
            coherence_score=coherence_score,
            memory_score=memory_score,
            safety_score=safety_score,
            usefulness_score=usefulness_score,
            traceability_score=traceability_score,
            errors=errors,
            warnings=list(dict.fromkeys(warnings)),
            recommendations=list(dict.fromkeys(recommendations)),
        )
