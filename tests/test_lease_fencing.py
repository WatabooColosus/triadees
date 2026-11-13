from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from triade.runtime.governed_task_executor import GovernedTaskExecutor
from triade.runtime.lease_heartbeat import LeaseHeartbeat
from triade.runtime.task_leases import AutonomousTaskStore


def _sleeping_handler(seconds: float) -> dict:
    time.sleep(seconds)
    return {"status": "completed"}


def _expire(db_path: Path, task_id: str) -> None:
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
            (expired, task_id),
        )


def test_long_task_renews_lease(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(db_path)
    task = store.enqueue("slow", {}, idempotency_key="slow")
    claimed = store.claim("worker-a", lease_seconds=1)
    assert claimed and store.start(
        task["task_id"], "worker-a", claimed["lease_generation"]
    )
    heartbeat = LeaseHeartbeat(
        store, task["task_id"], "worker-a", claimed["lease_generation"], 1
    )
    outcome = GovernedTaskExecutor(tmp_path / "quarantine").execute_callable(
        _sleeping_handler,
        args=(1.1,),
        timeout_seconds=3,
        artifact_dir=tmp_path / "artifact",
        heartbeat=heartbeat.renew,
        heartbeat_interval_seconds=heartbeat.interval_seconds,
    )
    assert outcome.status == "completed"
    with sqlite3.connect(db_path) as conn:
        renewals = conn.execute(
            "SELECT COUNT(*) FROM autonomous_lease_heartbeats WHERE renewed=1"
        ).fetchone()[0]
    assert renewals >= 2


def test_second_worker_cannot_claim_active_task(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    store.enqueue("work", {}, idempotency_key="one")
    assert store.claim("worker-a", lease_seconds=30)
    assert store.claim("worker-b", lease_seconds=30) is None


def test_stale_worker_cannot_complete_new_lease(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(db_path)
    task = store.enqueue("work", {}, idempotency_key="fenced")
    old = store.claim("worker-a", lease_seconds=1)
    assert old
    _expire(db_path, task["task_id"])
    assert store.recover_expired() == [task["task_id"]]
    new = store.claim("worker-b")
    assert new and new["lease_generation"] > old["lease_generation"]
    assert not store.complete(
        task["task_id"], "worker-a", old["lease_generation"], "old-result.json"
    )


def test_stale_worker_cannot_renew_new_generation(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(db_path)
    task = store.enqueue("work", {}, idempotency_key="renew-fence")
    old = store.claim("same-worker", lease_seconds=1)
    assert old
    _expire(db_path, task["task_id"])
    store.recover_expired()
    new = store.claim("same-worker")
    assert new
    assert not store.renew(task["task_id"], "same-worker", old["lease_generation"])


def test_recovered_task_rejects_old_result(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(db_path)
    task = store.enqueue("work", {}, idempotency_key="recovered")
    old = store.claim("worker-a", lease_seconds=1)
    assert old
    _expire(db_path, task["task_id"])
    store.recover_expired()
    assert not store.complete(
        task["task_id"], "worker-a", old["lease_generation"], "stale.json"
    )
    assert store.get(task["task_id"])["status"] == "recovered"


def test_lease_loss_cancels_execution(tmp_path: Path) -> None:
    calls = 0

    def lose_lease() -> bool:
        nonlocal calls
        calls += 1
        return False

    outcome = GovernedTaskExecutor(tmp_path / "quarantine").execute_callable(
        _sleeping_handler,
        args=(5.0,),
        timeout_seconds=10,
        artifact_dir=tmp_path / "artifact",
        heartbeat=lose_lease,
        heartbeat_interval_seconds=0.1,
    )
    assert calls == 1
    assert outcome.status == "lease_lost"
    assert outcome.termination_signal in {9, 15}
    assert outcome.elapsed_seconds < 2


def test_only_one_terminal_result_exists(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(db_path)
    task = store.enqueue("work", {}, idempotency_key="terminal")
    claimed = store.claim("worker-a")
    assert claimed
    generation = claimed["lease_generation"]
    result_ref = tmp_path / "result.json"
    result_ref.write_text("{}", encoding="utf-8")
    assert store.complete(task["task_id"], "worker-a", generation, str(result_ref))
    assert store.fail(task["task_id"], "worker-a", generation, "late") == {
        "status": "not_owner"
    }
    with sqlite3.connect(db_path) as conn:
        transitions = conn.execute(
            "SELECT COUNT(*) FROM autonomous_task_transitions WHERE task_id=?",
            (task["task_id"],),
        ).fetchone()[0]
    assert transitions == 1
