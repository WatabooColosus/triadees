"""Stop y lock de Living Workers."""

from __future__ import annotations

from pathlib import Path

from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop, lock_owner_status


def test_worker_lock_prevents_double_execution(tmp_path: Path) -> None:
    import os
    lock = tmp_path / "lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", lock_file=lock, stop_file=tmp_path / "stop")

    result = loop.run(WorkerRunConfig(lock_file=str(lock), stop_file=str(tmp_path / "stop"), runs_dir=str(tmp_path / "runs")))

    assert result["status"] == "locked"


def test_stale_worker_lock_is_recovered(tmp_path: Path, monkeypatch) -> None:
    lock = tmp_path / "lock"
    lock.write_text("99999999", encoding="utf-8")
    monkeypatch.setattr("triade.workers.worker_loop.check_ollama_blood", lambda: {})
    monkeypatch.setattr("triade.workers.worker_loop.ollama_blood_policy", lambda *_args: {"allowed": True, "degraded": False})
    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", lock_file=lock, stop_file=tmp_path / "stop")

    result = loop.run(WorkerRunConfig(max_iterations=1, once=True, lock_file=str(lock), stop_file=str(tmp_path / "stop"), runs_dir=str(tmp_path / "runs")))

    assert result["status"] in {"completed", "completed_with_errors"}
    assert lock_owner_status(lock)["active"] is False
    assert not lock.exists()


def test_worker_stop_file_prevents_start(tmp_path: Path) -> None:
    stop = tmp_path / "stop"
    stop.write_text("stop", encoding="utf-8")
    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", lock_file=tmp_path / "lock", stop_file=stop)

    result = loop.run(WorkerRunConfig(lock_file=str(tmp_path / "lock"), stop_file=str(stop), runs_dir=str(tmp_path / "runs")))

    assert result["status"] == "stopped"
