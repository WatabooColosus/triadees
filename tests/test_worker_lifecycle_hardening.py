from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from triade.runtime.cancellation import CancellationRequested, CancellationToken
from triade.runtime.governed_task_executor import GovernedTaskExecutor
from triade.runtime.process_lock import RuntimeProcessLock
from triade.runtime.task_leases import AutonomousTaskStore
from triade.workers.state_store import WorkerStateStore


def _slow(seconds: float) -> dict:
    time.sleep(seconds)
    return {"status": "completed"}


def test_structured_live_lock_verifies_command_line(tmp_path: Path) -> None:
    lock = tmp_path / "worker.lock"
    payload = json.loads(RuntimeProcessLock.payload(os.getpid()))
    payload["expected_token"] = "pytest"
    lock.write_text(json.dumps(payload), encoding="utf-8")
    result = WorkerStateStore(tmp_path / "db.sqlite").recover_interrupted_runtime(lock)
    assert result["status"] == "live_owner"
    assert lock.exists()


def test_pid_reuse_identity_mismatch_recovers_lock(tmp_path: Path) -> None:
    # Simula reutilización real de PID: el kernel garantiza que un proceso
    # distinto que reutiliza el mismo PID tiene un starttime distinto
    # (/proc/<pid>/stat campo 22), incluso si por coincidencia cmdline
    # fuera idéntico. Un expected_token constante (mecanismo previo) nunca
    # puede simular esto de forma realista porque nunca distingue procesos
    # reales entre sí — ver TECHNICAL_DEBT.md.
    lock = tmp_path / "worker.lock"
    payload = json.loads(RuntimeProcessLock.payload(os.getpid()))
    payload["start_time"] = (payload["start_time"] or 0) + 999999
    payload["expected_token"] = "definitely-not-this-process"
    lock.write_text(json.dumps(payload), encoding="utf-8")
    result = WorkerStateStore(tmp_path / "db.sqlite").recover_interrupted_runtime(lock)
    assert result["status"] == "recovered"
    assert not lock.exists()


def test_cancellation_token_checkpoint() -> None:
    token = CancellationToken()
    token.checkpoint()
    token.cancel()
    with pytest.raises(CancellationRequested):
        token.checkpoint()


def test_stop_cancels_live_child_process(tmp_path: Path) -> None:
    cancelled = False

    def stop_requested() -> bool:
        nonlocal cancelled
        cancelled = True
        return cancelled

    outcome = GovernedTaskExecutor(tmp_path / "quarantine").execute_callable(
        _slow,
        args=(10.0,),
        timeout_seconds=20,
        artifact_dir=tmp_path / "task",
        cancellation_check=stop_requested,
    )
    assert outcome.status == "cancelled"
    assert outcome.termination_signal in {9, 15}
    assert outcome.elapsed_seconds < 2


def test_killed_worker_lease_is_recovered(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    store = AutonomousTaskStore(db_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="recover-kill")
    assert store.claim("killed-worker", lease_seconds=1)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), task["task_id"]),
        )
    assert store.recover_expired() == [task["task_id"]]


def test_recovery_does_not_duplicate_effect_identity(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "db.sqlite")
    first = store.enqueue("pulse_check", {"effect": 1}, idempotency_key="same-effect")
    second = store.enqueue("pulse_check", {"effect": 1}, idempotency_key="same-effect")
    assert first["task_id"] == second["task_id"]
