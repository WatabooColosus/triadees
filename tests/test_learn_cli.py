"""Tests del CLI de aprendizaje controlado."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "triade_digimon.py"


def run_cli(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def write_run(run_path: Path) -> None:
    run_path.mkdir(parents=True)
    run_id = run_path.name
    (run_path / "input.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "user_input": "Explica como Tríade convierte runs en aprendizaje verificable.",
                "source": "test",
                "context": {"project_id": "triade"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_path / "output.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "response": "Tríade crea candidatos, evalúa utilidad y exige verificación antes de consolidar.",
                "actions_taken": ["plan_created", "template_fallback_response_generated"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run_path / "report.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    (run_path / "safety.json").write_text(json.dumps({"risk_level": "low"}), encoding="utf-8")


def test_learn_from_run_creates_evaluates_and_verifies_candidate(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    run_path = runs_dir / "run-test-learning"
    write_run(run_path)

    created = run_cli(
        "learn",
        "--db",
        str(db_path),
        "from-run",
        "run-test-learning",
        "--runs-dir",
        str(runs_dir),
        "--domain",
        "triade-learning",
    )

    assert created["status"] == "candidate"
    assert created["source_ref"] == "run:run-test-learning"
    assert "Tríade crea candidatos" in created["content"]

    candidate_id = created["candidate_id"]
    evaluated = run_cli("learn", "--db", str(db_path), "evaluate", candidate_id)
    assert evaluated["status"] == "evaluated"

    verified = run_cli("learn", "--db", str(db_path), "verify", candidate_id)
    assert verified["status"] == "verified"

    listed = run_cli("learn", "--db", str(db_path), "list", "--status", "verified", "--limit", "5")
    assert any(item["candidate_id"] == candidate_id for item in listed["candidates"])
