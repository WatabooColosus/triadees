from __future__ import annotations

from triade.core.response_coherence_gate import evaluate_response_coherence


def test_feedback_does_not_repeat_previous_answer() -> None:
    result = evaluate_response_coherence(
        user_input="muy bine, felicitaciones",
        proposed_response="Entendido. Colombia se encuentra en el continente de América del Sur. Si tienes más preguntas...",
        previous_user_input="en que continente queda colombia?",
        previous_response="Colombia se encuentra en el continente de América del Sur.",
        intent="conversation",
    )

    assert result["detected_input_type"] == "positive_feedback"
    assert result["should_reuse_previous_answer"] is False
    assert result["should_answer_factually"] is False
    assert result["should_acknowledge_feedback"] is True
    assert result["status"] in {"rewritten", "blocked"}
    assert "Colombia se encuentra" not in (result["final_response"] or "")
    assert "feedback" in (result["final_response"] or "").lower()


def test_follow_up_can_reuse_context_without_repeating_answer() -> None:
    result = evaluate_response_coherence(
        user_input="y cuál es su capital?",
        proposed_response="Bogotá.",
        previous_user_input="en que continente queda colombia?",
        previous_response="Colombia se encuentra en el continente de América del Sur.",
        intent="conversation",
    )

    assert result["detected_input_type"] == "follow_up"
    assert result["should_reuse_previous_answer"] is True
    assert result["should_answer_factually"] is True
    assert result["status"] in {"ok", "rewritten"}
    assert "Bogotá" in (result["final_response"] or "")


def test_thanks_and_acknowledgement_are_short() -> None:
    thanks = evaluate_response_coherence(
        user_input="gracias",
        proposed_response="Colombia se encuentra en el continente de América del Sur.",
        previous_user_input="en que continente queda colombia?",
        previous_response="Colombia se encuentra en el continente de América del Sur.",
        intent="conversation",
    )
    ack = evaluate_response_coherence(
        user_input="ok perfecto",
        proposed_response="Colombia se encuentra en el continente de América del Sur.",
        previous_user_input="en que continente queda colombia?",
        previous_response="Colombia se encuentra en el continente de América del Sur.",
        intent="conversation",
    )

    assert thanks["detected_input_type"] == "thanks"
    assert ack["detected_input_type"] == "acknowledgement"
    assert "Colombia se encuentra" not in (thanks["final_response"] or "")
    assert "Colombia se encuentra" not in (ack["final_response"] or "")


def test_central_detects_self_state_drift_for_unrelated_factual_question() -> None:
    from triade.core.central import Central

    assert Central._response_ignores_current_question(
        "entiendo, de que coilor es el sol?",
        "No siento como una persona. Mi Central coordina, el Hipotálamo interpreta y la evidencia queda en Cabina Viva.",
    ) is True
    assert Central._response_ignores_current_question(
        "¿cómo estás?",
        "No siento como una persona, pero estoy operando.",
    ) is False
