"""Tests de persistencia Living Workers."""

from __future__ import annotations

from pathlib import Path

from triade.workers.contracts import WorkerRunConfig
from triade.workers.state_store import WorkerStateStore


def test_worker_state_store_creates_tables_and_records_task(tmp_path: Path) -> None:
    store = WorkerStateStore(db_path=tmp_path / "triade.db")
    run = store.create_worker_run("worker-test", WorkerRunConfig(), tmp_path / "bg")
    task = store.enqueue_task("pulse_check", payload={"x": 1}, priority=5, run_ref="worker-test")
    claimed = store.claim_next_task()
    assert run["run_ref"] == "worker-test"
    assert task.id is not None
    assert claimed is not None
    assert claimed.task_type == "pulse_check"
    store.finish_task(claimed.id or 0, "completed", {"ok": True}, "approved", run_ref="worker-test")
    store.record_event("unit", "ok", run_ref="worker-test", task_id=claimed.id, task_type="pulse_check")
    store.finish_worker_run("worker-test", "completed", {"tasks_completed": 1})
    assert store.status()["task_counts"]["completed"] == 1
    assert store.list_events(run_ref="worker-test")[0]["event_type"] == "unit"
