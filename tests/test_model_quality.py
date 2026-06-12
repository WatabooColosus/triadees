"""Pruebas de estimadores de calidad de modelos."""

from __future__ import annotations

from triade.core.contracts import SignalPacket
from triade.core.model_quality import score_central, score_hypothalamus


def test_score_hypothalamus_rewards_valid_model_signal() -> None:
    signals = SignalPacket(
        run_id="run-test",
        intent="conversation",
        tone="calm",
        urgency="low",
        risk="low",
        pv7={str(i): 0.5 for i in range(7)},
        notes=["ok"],
    )

    assert score_hypothalamus(signals, {"ok": True}) == 1.0


def test_score_central_rewards_model_and_traceable_response() -> None:
    response = "Respuesta con memoria, riesgo y trazabilidad verificable para el usuario."

    assert score_central(response, model_ok=True) == 0.9


def test_score_central_keeps_short_template_lower() -> None:
    assert score_central("ok", model_ok=False) == 0.5
