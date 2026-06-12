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
        assert result["route"] in {"learning_candidate", "qualia_feedback", "episodic_memory", "ignore"}


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
