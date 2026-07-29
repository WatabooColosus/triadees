from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from triade.runtime.task_leases import AutonomousTaskStore


def test_idempotent_enqueue_returns_same_task(tmp_path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    first = store.enqueue("research", {"question": "q"}, idempotency_key="gap:1")
    second = store.enqueue("research", {"question": "q"}, idempotency_key="gap:1")
    assert first["task_id"] == second["task_id"]
    with sqlite3.connect(tmp_path / "tasks.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM autonomous_tasks").fetchone()[0] == 1


def test_two_workers_cannot_claim_same_task(tmp_path):
    path = tmp_path / "tasks.db"
    AutonomousTaskStore(path).enqueue("research", {}, idempotency_key="one")
    barrier = threading.Barrier(2)
    results = []

    def claim(worker):
        store = AutonomousTaskStore(path)
        barrier.wait()
        results.append(store.claim(worker, lease_seconds=30))

    threads = [threading.Thread(target=claim, args=(name,)) for name in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    claimed = [item for item in results if item is not None]
    assert len(claimed) == 1
    assert claimed[0]["worker_id"] in {"a", "b"}


def test_expired_lease_is_recovered_and_reclaimed(tmp_path):
    path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(path)
    task = store.enqueue("research", {}, idempotency_key="recover")
    assert store.claim("dead-worker", lease_seconds=30)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?", (expired, task["task_id"]))
    assert store.recover_expired() == [task["task_id"]]
    reclaimed = store.claim("new-worker")
    assert reclaimed and reclaimed["worker_id"] == "new-worker"
    assert reclaimed["attempt"] == 2


def test_retry_backoff_then_dead_letter(tmp_path):
    path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(path)
    task = store.enqueue("research", {}, idempotency_key="retry", max_attempts=2)
    claimed = store.claim("w")
    assert claimed
    retry = store.fail(task["task_id"], "w", "temporary", base_delay_seconds=0)
    assert retry["status"] == "retry_wait"
    claimed = store.claim("w")
    assert claimed
    dead = store.fail(task["task_id"], "w", "again", base_delay_seconds=0)
    assert dead["status"] == "dead_letter"
    assert store.claim("other") is None


def test_non_owner_cannot_complete_or_renew(tmp_path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("research", {}, idempotency_key="owned")
    store.claim("owner")
    assert store.renew(task["task_id"], "intruder") is False
    assert store.complete(task["task_id"], "intruder", "x") is False
    assert store.complete(task["task_id"], "owner", "artifact:1") is True
