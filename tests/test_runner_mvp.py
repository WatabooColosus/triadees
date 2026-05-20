"""Pruebas básicas del MVP real de Tríade Ω."""

from __future__ import annotations

import json
from pathlib import Path

from triade.core.runner import TriadeRunner


def test_runner_creates_auditable_run(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    db_path = tmp_path / "triade.db"
    runner = TriadeRunner(runs_dir=runs_dir, db_path=db_path)

    result = runner.run("Hola Tríade, crea memoria real")

    run_path = Path(result["run_path"])
    assert run_path.exists()
    assert (run_path / "input.json").exists()
    assert (run_path / "signals.json").exists()
    assert (run_path / "memory.json").exists()
    assert (run_path / "crystal.json").exists()
    assert (run_path / "plan.json").exists()
    assert (run_path / "safety.json").exists()
    assert (run_path / "output.json").exists()
    assert (run_path / "memory_diff.json").exists()
    assert (run_path / "report.json").exists()
    assert (run_path / "integrity.json").exists()
    assert (run_path / "CLOSED").exists()

    integrity = json.loads((run_path / "integrity.json").read_text(encoding="utf-8"))
    assert integrity["closed"] is True
    assert integrity["episode_id"] is not None
    assert integrity["signal_id"] is not None
    assert integrity["crystal_id"] is not None
    assert integrity["safety_id"] is not None
    assert integrity["verification_report_id"] is not None
    assert db_path.exists()


def test_recall_returns_recent_episode(tmp_path: Path) -> None:
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db")
    runner.run("Guardar episodio de prueba sobre memoria viva")

    recalled = runner.recall("memoria", limit=5)

    assert recalled["count"] >= 1
    assert "episodes" in recalled


def test_doctor_reports_full_persistence_counts(tmp_path: Path) -> None:
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db")
    runner.run("Doctor debe detectar persistencia completa")

    report = runner.doctor()

    assert report["status"] == "ok"
    assert report["db_exists"] is True
    assert report["schema_exists"] is True
    assert report["runs_dir_exists"] is True
    assert report["counts"]["runs"] >= 1
    assert report["counts"]["episodes"] >= 1
    assert report["counts"]["signals"] >= 1
    assert report["counts"]["crystals"] >= 1
    assert report["counts"]["safety_events"] >= 1
    assert report["counts"]["verification_reports"] >= 1
