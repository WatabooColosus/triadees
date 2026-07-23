"""Stop y lock de Living Workers."""

from __future__ import annotations

from pathlib import Path

from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def test_worker_lock_prevents_double_execution(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    lock.write_text("busy", encoding="utf-8")
    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", lock_file=lock, stop_file=tmp_path / "stop")

    result = loop.run(WorkerRunConfig(lock_file=str(lock), stop_file=str(tmp_path / "stop"), runs_dir=str(tmp_path / "runs")))

    assert result["status"] == "locked"


def test_worker_stop_file_prevents_start(tmp_path: Path) -> None:
    stop = tmp_path / "stop"
    stop.write_text("stop", encoding="utf-8")
    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", lock_file=tmp_path / "lock", stop_file=stop)

    result = loop.run(WorkerRunConfig(lock_file=str(tmp_path / "lock"), stop_file=str(stop), runs_dir=str(tmp_path / "runs")))

    assert result["status"] == "stopped"


def test_worker_recovers_stale_pid_lock(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    lock.write_text("99999999", encoding="utf-8")
    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", lock_file=lock, stop_file=tmp_path / "stop")

    result = loop.run(WorkerRunConfig(max_iterations=1, sleep_seconds=0, once=True,
                                      runs_dir=str(tmp_path / "runs"), lock_file=str(lock), stop_file=str(tmp_path / "stop")))

    assert result["status"] in {"completed", "completed_with_errors"}
    assert not lock.exists()
