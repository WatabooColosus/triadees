"""Tests de Model Router 1.6."""

from __future__ import annotations

from triade.models.model_router import ModelRouter


AVAILABLE = [
    "qwen2.5:3b-instruct",
    "qwen2.5-coder:3b",
    "nomic-embed-text:latest",
    "llama3:latest",
    "qwen3:1.7b",
]


def test_model_router_selects_hypothalamus_model() -> None:
    router = ModelRouter(AVAILABLE)
    decision = router.route("hypothalamus")

    assert decision.selected_model == "qwen2.5:3b-instruct"
    assert decision.fallback_used is False
    assert decision.role == "hypothalamus"


def test_model_router_selects_fast_model_for_urgent_central() -> None:
    router = ModelRouter(AVAILABLE)
    decision = router.route("central", urgency="high", prefer_speed=True)

    assert decision.role == "fast"
    assert decision.selected_model == "qwen3:1.7b"
    assert "velocidad" in decision.reason


def test_model_router_selects_deep_model_for_analysis() -> None:
    router = ModelRouter(AVAILABLE)
    decision = router.route("central", intent="analyze", prefer_depth=True)

    assert decision.role == "deep"
    assert decision.selected_model == "llama3:latest"
    assert "profundidad" in decision.reason


def test_model_router_selects_coder_model() -> None:
    router = ModelRouter(AVAILABLE)
    decision = router.route("coder")

    assert decision.selected_model == "qwen2.5-coder:3b"
    assert decision.role == "coder"


def test_model_router_uses_fallback_when_no_model_available() -> None:
    router = ModelRouter([])
    decision = router.route("central")

    assert decision.fallback_used is True
    assert decision.selected_model


def test_model_router_route_many() -> None:
    router = ModelRouter(AVAILABLE)
    payload = router.route_many(intent="analyze", urgency="medium")

    assert payload["intent"] == "analyze"
    assert "central" in payload["decisions"]
    assert "hypothalamus" in payload["decisions"]
    assert payload["decisions"]["coder"]["selected_model"] == "qwen2.5-coder:3b"
