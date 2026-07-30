"""Tests de Model Router sensible a hardware."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from triade.models.hardware_profile import HardwareProfile
from triade.models.model_router import ModelRouter

AVAILABLE = [
    "qwen2.5:3b-instruct",
    "qwen2.5-coder:3b",
    "nomic-embed-text:latest",
    "llama3:latest",
    "llama3.1:8b",
    "qwen3:1.7b",
]


def hw(tier: str, available: float) -> HardwareProfile:
    return HardwareProfile(
        cpu_count=8, ram_total_gb=16.0, ram_available_gb=available, tier=tier, notes=[]
    )


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
    assert decision.selected_model == "llama3.1:8b"
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


def test_low_hardware_rejects_heavy_deep_models() -> None:
    router = ModelRouter(AVAILABLE, hardware=hw("low", 3.0))
    decision = router.route("central", intent="analyze", prefer_depth=True)

    assert decision.role == "deep"
    assert decision.selected_model == "qwen2.5:3b-instruct"
    assert "llama3.1:8b" in decision.rejected_by_hardware
    assert decision.hardware_tier == "low"


def test_medium_hardware_allows_8b_when_available_memory_is_enough() -> None:
    router = ModelRouter(AVAILABLE, hardware=hw("medium", 9.0))
    decision = router.route("central", intent="analyze", prefer_depth=True)

    assert decision.selected_model == "llama3.1:8b"
    assert decision.hardware_tier == "medium"


def test_embedding_is_allowed_even_on_low_hardware() -> None:
    router = ModelRouter(AVAILABLE, hardware=hw("low", 1.5))
    decision = router.route("embedding")

    assert decision.selected_model == "nomic-embed-text:latest"
    assert decision.rejected_by_hardware == []


def test_measured_route_requires_active_status_and_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = tmp_path / "routing.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "active",
                "routes": {"summarizer": "qwen3:1.7b"},
                "benchmark_sha256": "abc",
                "evidence_ref": "evidence.json",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TRIADE_MEASURED_ROUTING_PATH", str(manifest))
    decision = ModelRouter(AVAILABLE).route("summarizer")
    assert decision.selected_model == "qwen3:1.7b"
    assert decision.reason == "measured_ab_route:abc"

    manifest.write_text(
        json.dumps(
            {"status": "rollback_baseline", "routes": {"summarizer": "qwen3:1.7b"}}
        ),
        encoding="utf-8",
    )
    fallback = ModelRouter(AVAILABLE).route("summarizer")
    assert fallback.reason != "measured_ab_route:abc"
