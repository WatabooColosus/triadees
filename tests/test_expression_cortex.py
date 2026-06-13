"""Tests de principios de la Corteza de Expresión — Tríade Ω.

Estos tests verifican principios generales de expresión, no respuestas fijas.
"""

import json
import pytest


# ── Tests unitarios de ExpressionCortex ─────────────────────────────────────

class TestExpressionCortexHidesInternalDumps:
    """FASE 7 — Test 1: La respuesta final no contiene dumps crudos."""

    def test_hides_bodega_global_dump(self):
        """Raw response con Bodega Global → response final sin dump."""
        from triade.core.expression_cortex import ExpressionCortex

        raw = (
            "He revisado tu código. Aquí están mis observaciones:\n\n"
            "bodega_global: {domain_count: 12, categories: ['code', 'docs'], ...}\n"
            "La función tiene algunos problemas de rendimiento."
        )
        result = ExpressionCortex().shape_response(
            user_input="revisa este código",
            raw_response=raw,
            intent="analyze",
            signals={},
            memory={},
            crystal={},
            qualia={},
            bodega_context={},
            learning_context={},
        )
        assert "bodega_global" not in result["response"], (
            "La respuesta final no debe contener dump de Bodega Global"
        )
        assert "problemas de rendimiento" in result["response"], (
            "La respuesta debe conservar el contenido conversacional"
        )
        assert result["hidden_evidence"]["raw_response"] == raw, (
            "La evidencia profunda debe conservar la respuesta cruda"
        )
        assert result["corrections"], "Debe haber correcciones registradas"

    def test_hides_qualia_bus_dump(self):
        """Raw response con QualiaBus → response final sin dump."""
        from triade.core.expression_cortex import ExpressionCortex

        raw = (
            "Basado en el contexto actual:\n"
            "qualia_signals: [{type: 'insight', confidence: 0.8}]\n"
            "qualia_experiences_count: 5\n"
            "Te recomiendo revisar la documentación primero."
        )
        result = ExpressionCortex().shape_response(
            user_input="qué debería hacer",
            raw_response=raw,
            intent="conversation",
            signals={},
            memory={},
            crystal={},
            qualia={},
            bodega_context={},
            learning_context={},
        )
        assert "qualia_signals" not in result["response"]
        assert "Te recomiendo" in result["response"]

    def test_hides_neuron_candidates_dump(self):
        """Raw response con candidatos de neuronas → response sin dump."""
        from triade.core.expression_cortex import ExpressionCortex

        raw = (
            "He identificado una oportunidad de mejora.\n"
            "neuron_candidate: {name: 'optimizador_API', confidence: 0.7}\n"
            "candidate_gate: {route: 'learning_candidate'}\n"
            "¿Quieres que profundice?"
        )
        result = ExpressionCortex().shape_response(
            user_input="mejora el API",
            raw_response=raw,
            intent="build_or_update",
            signals={},
            memory={},
            crystal={},
            qualia={},
            bodega_context={},
            learning_context={},
        )
        assert "neuron_candidate" not in result["response"]
        assert "¿Quieres que profundice?" in result["response"]

    def test_hides_json_block_dump(self):
        """Raw response con bloque JSON → sintetizado."""
        from triade.core.expression_cortex import ExpressionCortex

        raw = (
            "Resultado del análisis:\n\n"
            "```json\n{\"score\": 0.85, \"issues\": [\"memory leak\"]}\n```\n\n"
            "Sugiero corregir el memory leak primero."
        )
        result = ExpressionCortex().shape_response(
            user_input="analiza el sistema",
            raw_response=raw,
            intent="analyze",
            signals={},
            memory={},
            crystal={},
            qualia={},
            bodega_context={},
            learning_context={},
        )
        assert "```json" not in result["response"]
        assert "Sugiero corregir" in result["response"]


class TestCasualQuestionGetsNaturalSynthesis:
    """FASE 7 — Test 2: Pregunta casual → respuesta natural."""

    def test_casual_question_natural(self):
        """Input casual recibe respuesta natural, no dump técnico."""
        from triade.core.expression_cortex import ExpressionCortex

        result = ExpressionCortex().shape_response(
            user_input="como te sientes",
            raw_response="Me encuentro operativo. Todos los módulos funcionando correctamente.",
            intent="conversation",
            signals={},
            memory={"semantic_matches": 0, "confidence": 0.0},
            crystal={"temporal_status": "coherent", "status": "available"},
            qualia={"hypothesis_available": False, "status": "unavailable"},
            bodega_context={"domain_count": 5},
            learning_context={"active": True, "enabled": True},
        )
        assert result["expression_mode"] == "natural"
        assert len(result["visible_modular_trace"]) > 0
        assert "Central" in result["visible_modular_trace"] or "Hipotálamo" in result["visible_modular_trace"]

    def test_casual_question_no_candidates_list(self):
        """Respuesta natural no lista candidatos ni políticas."""
        from triade.core.expression_cortex import ExpressionCortex

        raw = (
            "Estoy bien. El sistema está estable.\n"
            "background_neuron_candidates: [proyecto_X, refactor_Y]\n"
            "Mi temperatura es normal y la memoria está disponible."
        )
        result = ExpressionCortex().shape_response(
            user_input="cómo estás",
            raw_response=raw,
            intent="conversation",
            signals={},
            memory={},
            crystal={},
            qualia={},
            bodega_context={},
            learning_context={},
        )
        assert "background_neuron_candidates" not in result["response"]
        assert "No siento como una persona" in result["response"]
        assert "Central" in result["response"]
        assert "Bodega" in result["response"]


class TestDiagnosticQuestionAllowsSummary:
    """FASE 7 — Test 3: Pregunta de diagnóstico → resumen técnico."""

    def test_diagnostic_question_technical_summary(self):
        """Input de diagnóstico permite modo técnico sin dump infinito."""
        from triade.core.expression_cortex import ExpressionCortex

        result = ExpressionCortex().shape_response(
            user_input="verifica sistema",
            raw_response="Estado del sistema: CPU 45%, RAM 8GB libres, disco 120GB, Ollama conectado.",
            intent="analyze",
            signals={},
            memory={},
            crystal={},
            qualia={},
            bodega_context={},
            learning_context={},
        )
        assert result["expression_mode"] == "diagnostic"

    def test_diagnostic_not_infinite_dump(self):
        """Diagnóstico no se convierte en dump interno infinito."""
        from triade.core.expression_cortex import ExpressionCortex

        raw = (
            "Estado del servidor:\n"
            "CPU: 45% | RAM: 8.2 GB | Disco: 120 GB libres\n"
            "Ollama: conectado | Modelo: qwen2.5:3b\n"
            "Bodega Global: {domain_count: 12, total_episodes: 345, ...}\n"
            "system_events: [{type: 'info', message: 'todo ok'}]\n"
            "readiness_report: {score: 0.92, status: 'ready'}\n"
            "Resumen: el sistema responde correctamente."
        )
        result = ExpressionCortex().shape_response(
            user_input="audita repo",
            raw_response=raw,
            intent="analyze",
            signals={},
            memory={},
            crystal={},
            qualia={},
            bodega_context={},
            learning_context={},
        )
        assert "Bodega Global" not in result["response"]
        assert "system_events" not in result["response"]
        assert "Resumen" in result["response"] or "responde" in result["response"]


class TestFactualQuestionStaysFactual:
    """FASE 7 — Test 4: Pregunta factual no cambia el tema a Tríade."""

    def test_factual_question_factual_content(self):
        """Pregunta factual responde sobre el tema, no sobre Tríade."""
        from triade.core.expression_cortex import ExpressionCortex

        result = ExpressionCortex().shape_response(
            user_input="cómo vuela un ave",
            raw_response="Las aves vuelan gracias a la forma de sus alas, que generan sustentación. "
                         "El aire pasa más rápido por la parte superior del ala, creando presión "
                         "diferencial que las eleva.",
            intent="conversation",
            signals={},
            memory={},
            crystal={},
            qualia={},
            bodega_context={},
            learning_context={},
        )
        assert result["expression_mode"] == "technical_summary"
        assert "ave" in result["response"] or "alas" in result["response"]


class TestLearningPipelineIntact:
    """FASE 7 — Test 5: El aprendizaje NO se bloquea por la Corteza."""

    def test_learning_pipeline_still_records(self):
        """La Corteza no interfiere con el pipeline de aprendizaje."""
        from triade.core.expression_cortex import ExpressionCortex

        raw = "He analizado tu código. Hay un patrón que podríamos mejorar."
        result = ExpressionCortex().shape_response(
            user_input="revisa mi código",
            raw_response=raw,
            intent="analyze",
            signals={},
            memory={},
            crystal={},
            qualia={},
            bodega_context={},
            learning_context={},
        )
        assert result["response"] == raw, (
            "Si no hay dumps, la respuesta no debe modificarse"
        )
        assert result["hidden_evidence"]["raw_response"] == raw
        assert result["internal_context_used"] is True

    def test_hidden_evidence_preserves_raw(self):
        """hidden_evidence preserva toda la info para el pipeline de aprendizaje."""
        from triade.core.expression_cortex import ExpressionCortex

        raw = "Resultado: score 0.85\nmemory_trace: {last_query: 'optimize', confidence: 0.9}"
        result = ExpressionCortex().shape_response(
            user_input="optimiza esto",
            raw_response=raw,
            intent="build_or_update",
            signals={"intent": "build_or_update", "hypothalamus_quality": 0.8},
            memory={"semantic_matches": 3, "confidence": 0.75},
            crystal={"temporal_status": "coherent", "status": "available"},
            qualia={"hypothesis_available": True, "status": "available"},
            bodega_context={"domain_count": 10},
            learning_context={"active": True, "enabled": True},
        )
        he = result["hidden_evidence"]
        assert "raw_response" in he
        assert "signals" in he
        assert "memory" in he
        assert "crystal" in he
        assert "qualia" in he
        assert "bodega_context" in he
        assert "learning_context" in he
        assert he["memory"]["semantic_matches"] == 3
        assert he["qualia"]["hypothesis_available"] is True


class TestExpressionModeDetection:
    """Verifica que el modo de expresión se detecte correctamente."""

    def test_diagnostic_keyword_detection(self):
        from triade.core.expression_cortex import ExpressionCortex

        for keyword in ["audita", "diagnóstico", "verifica", "status", "health", "revisa"]:
            result = ExpressionCortex().shape_response(
                user_input=f"{keyword} el sistema",
                raw_response="Todo funciona correctamente.",
                intent="conversation",
                signals={}, memory={}, crystal={}, qualia={},
                bodega_context={}, learning_context={},
            )
            assert result["expression_mode"] == "diagnostic", (
                f"'{keyword}' debería detectarse como diagnostic"
            )

    def test_technical_question_detection(self):
        from triade.core.expression_cortex import ExpressionCortex

        for keyword in ["cómo funciona", "qué es", "define"]:
            result = ExpressionCortex().shape_response(
                user_input=f"{keyword} un motor eléctrico",
                raw_response="Un motor eléctrico funciona mediante...",
                intent="conversation",
                signals={}, memory={}, crystal={}, qualia={},
                bodega_context={}, learning_context={},
            )
            assert result["expression_mode"] == "technical_summary", (
                f"'{keyword}' debería detectarse como technical_summary"
            )

    def test_creative_question_detection(self):
        from triade.core.expression_cortex import ExpressionCortex

        for keyword in ["crea", "inventa", "imagina", "sugiere", "idea"]:
            result = ExpressionCortex().shape_response(
                user_input=f"{keyword} una historia",
                raw_response="Aquí tienes una idea creativa...",
                intent="conversation",
                signals={}, memory={}, crystal={}, qualia={},
                bodega_context={}, learning_context={},
            )
            assert result["expression_mode"] == "creative", (
                f"'{keyword}' debería detectarse como creative"
            )
