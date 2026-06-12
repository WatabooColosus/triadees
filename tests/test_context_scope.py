"""Pruebas del alcance contextual usado por el Cristal."""

from __future__ import annotations

from triade.core.context_scope import build_comparison_basis
from triade.core.contracts import InputPacket


def test_context_scope_defaults_to_source_intent() -> None:
    packet = InputPacket(user_input="hola", source="api")

    basis = build_comparison_basis(packet, "conversation")

    assert basis["context_scope"] == "source_intent"
    assert basis["context_key"] == "source_intent|intent=conversation|source=api"


def test_context_scope_uses_project_neuron_when_available() -> None:
    packet = InputPacket(
        user_input="analiza",
        source="api",
        context={"project_id": "triade", "active_neuron": "cristal"},
    )

    basis = build_comparison_basis(packet, "analyze")

    assert basis["context_scope"] == "project_neuron"
    assert basis["context_key"] == "project_neuron|intent=analyze|project_id=triade|active_neuron=cristal"


def test_context_scope_ignores_invalid_explicit_scope() -> None:
    packet = InputPacket(
        user_input="analiza",
        source="api",
        context={"context_scope": "invalid", "session_id": "s1"},
    )

    basis = build_comparison_basis(packet, "analyze")

    assert basis["context_scope"] == "session"
    assert basis["context_key"] == "session|intent=analyze|session_id=s1"
