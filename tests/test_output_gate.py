"""Pruebas del filtro de salida al usuario."""

from __future__ import annotations

from triade.core.output_gate import sanitize_user_response


def test_output_gate_keeps_clean_response() -> None:
    result = sanitize_user_response("Respuesta natural para el usuario.", "hola", "conversation")

    assert result == {
        "response": "Respuesta natural para el usuario.",
        "modified": False,
        "reason": "clean",
    }


def test_output_gate_replaces_empty_response() -> None:
    result = sanitize_user_response("  ", "hola", "conversation")

    assert result["modified"] is True
    assert result["reason"] == "empty_response"
    assert result["response"] == "Recibido. Estoy listo para ayudarte."


def test_output_gate_blocks_internal_report_leak() -> None:
    result = sanitize_user_response(
        "### Contexto\n- **q_crystal**: 0.7\n- **plan details**: interno",
        "hola",
        "conversation",
    )

    assert result["modified"] is True
    assert result["reason"] == "internal_leak_detected"
    assert result["response"] == "Hola, soy Tríade Ω. Estoy contigo y listo para ayudarte."


def test_output_gate_allows_operational_awareness_when_requested() -> None:
    text = "Pulso vivo activo. Bodega semántica lista."

    result = sanitize_user_response(text, "estado de memoria y pulso", "analyze")

    assert result == {
        "response": text,
        "modified": False,
        "reason": "operational_awareness_allowed",
    }
