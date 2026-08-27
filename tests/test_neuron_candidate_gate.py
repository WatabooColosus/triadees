from __future__ import annotations

from triade.core.neuron_candidate_gate import evaluate_neuron_candidate_worthiness

NO_NEURON_CASES = [
    "en que continente queda colombia?",
    "muy bine, felicitaciones",
    "gracias",
    "ok perfecto",
    "cuanto es 2+2?",
    "qué significa fotosíntesis?",
]


def test_gate_blocks_simple_inputs() -> None:
    for text in NO_NEURON_CASES:
        result = evaluate_neuron_candidate_worthiness(
            user_input=text,
            intent="conversation",
            domain="general",
            response="",
            context={},
        )
        assert result["should_create_neuron"] is False, text
        assert result["route"] in {
            "learning_candidate",
            "qualia_feedback",
            "episodic_memory",
            "ignore",
        }


def test_gate_allows_explicit_operational_neuron_request() -> None:
    result = evaluate_neuron_candidate_worthiness(
        user_input="crea una neurona para auditar memoria y evitar contradicciones",
        intent="build_or_update",
        domain="memory_governance",
        response="",
        context={},
    )

    assert result["should_create_neuron"] is True
    assert result["route"] == "neuron"
    assert result["suggested_name"]
    assert result["suggested_domain"] == "memory_governance"
    assert "evidence" in " ".join(result["required_evidence"])


def test_gate_allows_domain_specific_recurrent_need() -> None:
    result = evaluate_neuron_candidate_worthiness(
        user_input="necesito una neurona para Xiaos Medellín que aprenda diseño gráfico y ventas",
        intent="build_or_update",
        domain="business_support",
        response="",
        context={},
    )

    assert result["should_create_neuron"] is True
    assert result["route"] == "neuron"
    assert result["score"] >= 0.75


# ── §18: regresiones sobre casos reales de la batería conversacional ────────

from triade.core.neuron_candidate_gate import (  # noqa: E402
    _detect_type,
    _looks_like_factual_simple,
)


def test_gracias_a_causal_no_es_agradecimiento():
    """§18.1 — input real que el sistema contestó con «De nada. Seguimos.»

    `gracias a` es una locución preposicional causal. La comparación era por
    subcadena, así que cualquier frase que la contuviera se clasificaba como
    agradecimiento y se descartaba sin procesarla.
    """
    texto = (
        "Dime una cosa concreta que hayas aprendido gracias a nuestras "
        "conversaciones y explícame qué evidencia lo demuestra"
    )
    assert _detect_type(texto) != "thanks"


def test_gracias_a_secas_si_es_agradecimiento():
    """§18.2 — la reparación no puede romper el caso legítimo."""
    assert _detect_type("gracias") == "thanks"
    assert _detect_type("muchas gracias, muy útil") == "thanks"
    assert _detect_type("ok, gracias") == "thanks"


def test_gracias_a_una_persona_sigue_siendo_agradecimiento():
    """`gracias a ti` agradece: el complemento es persona, no causa."""
    assert _detect_type("gracias a ti por la ayuda") == "thanks"


def test_pregunta_operativa_compleja_no_es_factual_simple():
    """§18.3 — empezar por «qué» no convierte una pregunta en trivial.

    Los tres son inputs reales que acabaron en `factual_simple`, y con ello en
    `score=0.15` y el motivo «no debería crear neurona»: cierto, pero por el
    motivo equivocado, y descartando la ruta operativa.
    """
    for texto in (
        "¿Qué le falta a una neurona para pasar a funcional?",
        "¿Qué mejora deberías realizar sobre tu propio funcionamiento?",
        "¿Hay una capacidad que justifique entrenar LoRA en vez de prompting?",
    ):
        assert not _looks_like_factual_simple(texto), texto
        assert _detect_type(texto) == "operational_question", texto


def test_una_pregunta_factual_de_verdad_sigue_siendo_factual():
    """La reparación no puede tragarse el caso que sí era simple."""
    for texto in ("¿Cuál es la capital de Francia?", "¿Qué hora es?"):
        assert _looks_like_factual_simple(texto), texto
        assert _detect_type(texto) == "factual_simple", texto


def test_la_pregunta_operativa_se_enruta_con_su_propio_motivo():
    """No crea neurona, pero tampoco se despacha como trivial."""
    veredicto = evaluate_neuron_candidate_worthiness(
        "¿Qué le falta a una neurona para pasar a funcional?",
        intent="analyze",
    )
    assert veredicto["should_create_neuron"] is False
    assert veredicto["route"] == "learning_candidate"
    assert (
        veredicto["reason"]
        == "operational_question_needs_system_state_not_a_new_neuron"
    )
    assert veredicto["score"] > 0.15, "no puede valer lo mismo que una trivial"
