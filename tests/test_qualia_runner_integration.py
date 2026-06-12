import json
from pathlib import Path

from triade.core.runner import TriadeRunner


def test_runner_writes_qualia_artifacts_and_memory_diff(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)
    result = runner.run("Crea aprendizaje Qualia para este run")
    run_path = Path(result["run_path"])
    assert (run_path / "qualia_experiences.json").exists()
    assert (run_path / "qualia_state.json").exists()
    assert result["memory_diff"]["qualia_experiences_count"] >= 1
    state = json.loads((run_path / "qualia_state.json").read_text(encoding="utf-8"))
    assert state["run_id"] == result["run_id"]


def test_runner_plan_includes_qualia_hypothesis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)
    result = runner.run("Analiza este input para qualia hypothesis")
    run_path = Path(result["run_path"])
    plan_path = run_path / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        assert "qualia_hypothesis" in plan


def test_runner_qualia_state_in_memory_diff(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_POST_RUN_LEARNING", "1")
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)
    result = runner.run("Input para verificar qualia state en memory diff")
    md = result["memory_diff"]
    assert "qualia_state" in md
    assert "qualia_experiences_count" in md
    assert "qualia_signals_count" in md
