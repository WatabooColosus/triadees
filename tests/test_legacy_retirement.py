from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from triade.runtime.legacy_compatibility import LegacyCompatibilityController
from triade.workers.state_store import WorkerStateStore
from triade.workers.task_queue import WorkerTaskQueue


def _count(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_v2_queue_is_default_and_does_not_write_legacy(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    queue = WorkerTaskQueue(db_path)
    task = queue.enqueue("pulse_check", {"cycle": 1}, run_ref="run-1")
    assert isinstance(task.id, str)
    assert _count(db_path, "autonomous_tasks") == 1
    assert _count(db_path, "worker_tasks") == 0
    assert LegacyCompatibilityController(db_path).status()["mode"] == "v2_canonical"


def test_direct_legacy_write_is_blocked_by_sqlite_trigger(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    store = WorkerStateStore(db_path)
    with pytest.raises(
        sqlite3.IntegrityError, match="legacy_worker_task_writes_disabled"
    ):
        store.enqueue_task("pulse_check", {})
    assert _count(db_path, "worker_tasks") == 0


def test_compatibility_rollback_restores_and_retires_legacy_writes(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "tasks.db"
    store = WorkerStateStore(db_path)
    controller = LegacyCompatibilityController(db_path)
    enabled = controller.set_compatibility(
        enabled=True, actor="operator", reason="bounded rollback drill"
    )
    assert enabled["legacy_writes_enabled"] == 1
    legacy = store.enqueue_task("pulse_check", {"compatibility": True})
    assert legacy.id is not None
    disabled = controller.set_compatibility(
        enabled=False, actor="operator", reason="rollback drill complete"
    )
    assert disabled["legacy_writes_enabled"] == 0
    with pytest.raises(
        sqlite3.IntegrityError, match="legacy_worker_task_writes_disabled"
    ):
        store.enqueue_task("pulse_check", {"blocked_again": True})
    metrics = controller.metrics()
    assert metrics["legacy_total"] == 1
    assert metrics["duplicate_links"] == 0


def test_canonical_enqueue_is_idempotent_while_active(tmp_path: Path) -> None:
    queue = WorkerTaskQueue(tmp_path / "tasks.db")
    first = queue.enqueue("pulse_check", {"cycle": 1}, run_ref="run-1")
    second = queue.enqueue("pulse_check", {"cycle": 1}, run_ref="run-1")
    assert second.id == first.id
    assert len(queue.list()) == 1
