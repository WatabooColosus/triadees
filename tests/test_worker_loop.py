"""Tests del loop Living Workers."""

from __future__ import annotations

from pathlib import Path

from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def test_worker_loop_once_runs_all_default_tasks(tmp_path: Path) -> None:
    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", lock_file=tmp_path / "lock", stop_file=tmp_path / "stop")

    result = loop.run(WorkerRunConfig(max_iterations=1, sleep_seconds=0, once=True, runs_dir=str(tmp_path / "runs"), lock_file=str(tmp_path / "lock"), stop_file=str(tmp_path / "stop")))

    assert result["status"] == "completed"
    assert result["tasks_completed"] == 10
    assert (Path(result["artifact_dir"]) / "summary.json").exists()
