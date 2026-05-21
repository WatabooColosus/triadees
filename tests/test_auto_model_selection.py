"""Tests de auto selección de modelos en Runner."""

from __future__ import annotations

from triade.core.runner import TriadeRunner


def test_runner_reports_model_selection_when_ollama_disabled() -> None:
    runner = TriadeRunner(use_ollama=False, auto_select_models=True)

    assert runner.model_selection["enabled"] is False
    assert runner.model_selection["reason"] == "manual_model_provided_or_ollama_disabled"
    assert runner.hypothalamus_model
    assert runner.central_model


def test_runner_result_contains_model_selection(tmp_path) -> None:
    runner = TriadeRunner(runs_dir=tmp_path, use_ollama=False, auto_select_models=True)
    result = runner.run("Prueba auto selección sin Ollama", source="test")

    assert "model_selection" in result
    assert "model_selection" in result["memory_diff"]
    assert result["model_selection"]["enabled"] is False
