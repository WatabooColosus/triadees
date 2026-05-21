"""Tests de matriz de compatibilidad de modelos."""

from __future__ import annotations

from triade.models.compatibility_matrix import ModelCompatibilityMatrix
from triade.models.hardware_profile import HardwareProfile


def hw(tier: str, available: float) -> HardwareProfile:
    return HardwareProfile(cpu_count=8, ram_total_gb=16.0, ram_available_gb=available, tier=tier, notes=[])


def test_compatibility_matrix_builds_counts() -> None:
    matrix = ModelCompatibilityMatrix(hw("medium", 8.0), available_models=["qwen2.5:3b-instruct"])
    payload = matrix.build()

    assert "counts" in payload
    assert "models" in payload
    assert payload["counts"]["recommended"] >= 1


def test_heavy_model_blocked_when_ram_is_low() -> None:
    matrix = ModelCompatibilityMatrix(hw("low", 2.0), available_models=["llama3.1:8b"])
    result = matrix.evaluate_model("llama3.1:8b")

    assert result.status in {"blocked", "risky"}
    assert result.warnings


def test_embedding_model_allowed_even_when_not_installed() -> None:
    matrix = ModelCompatibilityMatrix(hw("low", 1.5), available_models=[])
    result = matrix.evaluate_model("nomic-embed-text:latest")

    assert result.status in {"allowed", "recommended"}
    assert "embedding" in result.recommended_roles


def test_installed_small_model_recommended_on_medium() -> None:
    matrix = ModelCompatibilityMatrix(hw("medium", 8.0), available_models=["qwen2.5:3b-instruct"])
    result = matrix.evaluate_model("qwen2.5:3b-instruct")

    assert result.installed is True
    assert result.status == "recommended"
