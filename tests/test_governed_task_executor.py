from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from triade.runtime.governed_task_executor import GovernedTaskExecutor
from triade.runtime.task_leases import AutonomousTaskStore
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def _slow_handler(partial_path: str, seconds: float) -> dict:
    Path(partial_path).write_text("partial", encoding="utf-8")
    time.sleep(seconds)
    return {"status": "completed"}


def _quick_handler() -> dict:
    return {"status": "completed", "evidence": "real"}


def test_handler_is_terminated_after_timeout(tmp_path: Path) -> None:
    executor = GovernedTaskExecutor(tmp_path / "quarantine")
    artifact = tmp_path / "task"
    started = time.monotonic()
    outcome = executor.execute_callable(
        _slow_handler,
        args=(str(artifact / "partial.txt"), 3.0),
        timeout_seconds=0.2,
        artifact_dir=artifact,
    )
    elapsed = time.monotonic() - started

    assert outcome.status == "timeout"
    assert elapsed < 2.0
    assert outcome.termination_signal in {15, 9}


def test_timeout_does_not_wait_for_handler_completion(tmp_path: Path) -> None:
    outcome = GovernedTaskExecutor(tmp_path / "quarantine").execute_callable(
        _slow_handler,
        args=(str(tmp_path / "task" / "partial.txt"), 5.0),
        timeout_seconds=0.1,
        artifact_dir=tmp_path / "task",
    )
    assert outcome.elapsed_seconds < 2.0


def test_timeout_never_publishes_completed(tmp_path: Path) -> None:
    outcome = GovernedTaskExecutor(tmp_path / "quarantine").execute_callable(
        _slow_handler,
        args=(str(tmp_path / "task" / "partial.txt"), 2.0),
        timeout_seconds=0.1,
        artifact_dir=tmp_path / "task",
    )
    assert outcome.status == "timeout"
    assert outcome.result == {}


def test_timeout_produces_retry_or_dead_letter(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("pulse_check", {}, idempotency_key="timeout", max_attempts=1)
    claimed = store.claim("worker")
    assert claimed and store.start(
        task["task_id"], "worker", claimed["lease_generation"]
    )
    assert store.mark_timeout(
        task["task_id"],
        "worker",
        claimed["lease_generation"],
        "deadline",
        retryable=True,
    )
    assert store.get(task["task_id"])["status"] == "dead_letter"


def test_worker_timeout_never_publishes_completed(tmp_path: Path) -> None:
    db = tmp_path / "worker.db"
    loop = WorkerLoop(
        db_path=db,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )
    loop.queue.enqueue("pulse_check", {"verification": "real_timeout"})
    loop.run(
        WorkerRunConfig(
            once=True,
            max_iterations=1,
            task_timeout=0.001,
            runs_dir=str(tmp_path / "runs"),
            lock_file=str(tmp_path / "lock"),
            stop_file=str(tmp_path / "stop"),
        )
    )
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM autonomous_tasks ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    assert row["status"] == "retry_wait"


def test_timeout_moves_partial_artifacts_to_quarantine(tmp_path: Path) -> None:
    artifact = tmp_path / "task"
    outcome = GovernedTaskExecutor(tmp_path / "quarantine").execute_callable(
        _slow_handler,
        args=(str(artifact / "partial.txt"), 3.0),
        timeout_seconds=1.0,
        artifact_dir=artifact,
    )
    quarantine = Path(str(outcome.quarantine_ref))
    assert not artifact.exists()
    assert (quarantine / "partial.txt").read_text(encoding="utf-8") == "partial"
    assert (quarantine / "quarantine.json").exists()


def test_completed_callable_collects_real_result(tmp_path: Path) -> None:
    outcome = GovernedTaskExecutor(tmp_path / "quarantine").execute_callable(
        _quick_handler,
        timeout_seconds=2.0,
        artifact_dir=tmp_path / "task",
    )
    assert outcome.status == "completed"
    assert outcome.result["evidence"] == "real"
    assert outcome.exit_code == 0


def test_subprocess_children_are_terminated(tmp_path: Path) -> None:
    script = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "print(p.pid, flush=True); time.sleep(30)"
    )
    outcome = GovernedTaskExecutor(tmp_path / "quarantine").execute_subprocess(
        [sys.executable, "-c", script],
        timeout_seconds=0.5,
        artifact_dir=tmp_path / "subprocess",
    )
    assert outcome.status == "timeout"
    stdout = Path(str(outcome.stdout_ref)).read_text(encoding="utf-8").strip()
    child_pid = int(stdout.splitlines()[0])
    for _ in range(20):
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        status = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(child_pid)],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert not status or status.startswith("Z")
