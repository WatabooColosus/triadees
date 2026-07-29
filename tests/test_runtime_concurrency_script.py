from __future__ import annotations

from pathlib import Path

from scripts.run_runtime_concurrency_test import run_concurrency_validation


def test_reduced_runtime_concurrency(tmp_path: Path) -> None:
    output = tmp_path / "run"
    report = run_concurrency_validation(output, task_count=20, worker_count=2)
    assert report["duplicate_effects"] == 0
    assert report["recovered_leases"] == 1
    assert report["missing_artifacts"] == 0
    assert report["db_integrity"] == "ok"
    assert report["all_accounted"] is True
    repeated = run_concurrency_validation(output, task_count=20, worker_count=2)
    assert repeated["run_directory"] != report["run_directory"]
    assert repeated["all_accounted"] is True
