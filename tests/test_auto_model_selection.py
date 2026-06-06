"""Tests de auto selección de modelos en Runner."""

from __future__ import annotations

import sqlite3

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


def test_runner_logs_hypothalamus_and_central_fallback_model_events(tmp_path) -> None:
    db_path = tmp_path / "triade.db"
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=db_path, use_ollama=False, auto_select_models=True)

    result = runner.run("Prueba fallback controlado", source="test")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT role, provider, model_name, ok, quality_score FROM model_events WHERE run_id = ? ORDER BY role",
            (result["run_id"],),
        ).fetchall()
    assert rows == [
        ("central", "template", "template-fallback", 0, result["models"]["central"]["quality_score"]),
        ("hypothalamus", "rules", "rules-fallback", 0, result["models"]["hypothalamus"]["quality_score"]),
    ]
    assert result["models"]["hypothalamus"]["provider"] == "rules"
    assert result["models"]["central"]["provider"] == "template"


def test_runner_doctor_reports_double_model_selection(tmp_path) -> None:
    runner = TriadeRunner(
        runs_dir=tmp_path / "runs",
        db_path=tmp_path / "triade.db",
        use_ollama=False,
        hypothalamus_model="hyp-test",
        central_model="central-test",
    )

    doctor = runner.doctor()

    assert doctor["models"]["hypothalamus"] == "hyp-test"
    assert doctor["models"]["central"] == "central-test"
    assert doctor["models"]["selection"]["reason"] == "manual_model_provided_or_ollama_disabled"
    assert doctor["models"]["ollama"]["disabled"] is True
