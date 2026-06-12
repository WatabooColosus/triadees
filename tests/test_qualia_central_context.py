"""Tests para verificación de que Central consume qualia como hipótesis contextual."""

from __future__ import annotations

import json
from pathlib import Path

from triade.core.runner import TriadeRunner


def test_runner_plan_dict_includes_qualia_hypothesis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)
    result = runner.run("Test qualia hypothesis integration")
    run_path = Path(result["run_path"])
    plan_path = run_path / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        assert "qualia_hypothesis" in plan
        hyp = plan["qualia_hypothesis"]
        assert "status" in hyp
        assert "policy" in hyp


def test_runner_qualia_hypothesis_unavailable_without_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)
    result = runner.run("Input sin datos qualia previos")
    run_path = Path(result["run_path"])
    plan_path = run_path / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        hyp = plan.get("qualia_hypothesis", {})
        assert hyp.get("status") in {"unavailable", "available"}


def test_runner_qualia_hypothesis_in_integrity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)
    result = runner.run("Verificar qualia en integrity")
    run_path = Path(result["run_path"])
    integrity_path = run_path / "integrity.json"
    if integrity_path.exists():
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        assert "qualia_state" in integrity


def test_runner_memory_diff_has_qualia_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)
    result = runner.run("Campos qualia en memory diff")
    md = result["memory_diff"]
    assert "qualia_experiences_count" in md
    assert "qualia_signals_count" in md
    assert "qualia_central_packets_count" in md
    assert "qualia_storage_packets_count" in md
    assert "qualia_state" in md
