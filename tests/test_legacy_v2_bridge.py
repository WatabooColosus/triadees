from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.runtime.legacy_compatibility import LegacyCompatibilityController
from triade.runtime.legacy_task_reconciler import LegacyTaskReconciler
from triade.runtime.task_leases import AutonomousTaskStore
from triade.workers.state_store import WorkerStateStore


def _delegated(
    db_path: Path, key: str = "legacy:1"
) -> tuple[WorkerStateStore, dict, int]:
    legacy = WorkerStateStore(db_path)
    LegacyCompatibilityController(db_path).set_compatibility(
        enabled=True, actor="test", reason="legacy bridge fixture"
    )
    queued = legacy.enqueue_task("pulse_check", {"value": 1})
    claimed = legacy.claim_next_task()
    assert claimed and claimed.id == queued.id
    v2 = AutonomousTaskStore(db_path).enqueue(
        "pulse_check", {"value": 1}, idempotency_key=key
    )
    assert legacy.link_delegated_task(int(queued.id or 0), v2["task_id"])
    return legacy, v2, int(queued.id or 0)


def _legacy_row(db_path: Path, legacy_id: int) -> sqlite3.Row:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM worker_tasks WHERE id=?", (legacy_id,)
        ).fetchone()
    assert row is not None
    return row


def test_legacy_task_links_to_v2(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    _legacy, v2, legacy_id = _delegated(db_path)
    row = _legacy_row(db_path, legacy_id)
    assert row["autonomous_task_id"] == v2["task_id"]
    assert row["migration_status"] == "delegated"


def test_lease_conflict_returns_legacy_to_safe_state(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    legacy, v2, legacy_id = _delegated(db_path)
    assert AutonomousTaskStore(db_path).claim_task(v2["task_id"], "other")
    legacy.return_delegation_to_pending(legacy_id, "v2_lease_conflict")
    row = _legacy_row(db_path, legacy_id)
    assert row["status"] == "pending"
    assert row["migration_status"] == "pending"


def test_reconciler_repairs_stuck_legacy_task(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    legacy = WorkerStateStore(db_path)
    LegacyCompatibilityController(db_path).set_compatibility(
        enabled=True, actor="test", reason="legacy bridge fixture"
    )
    task = legacy.enqueue_task("pulse_check", {})
    legacy.claim_next_task()
    result = LegacyTaskReconciler(db_path).reconcile()
    assert result["repaired"] == 1
    assert _legacy_row(db_path, int(task.id or 0))["status"] == "pending"


def test_v2_is_canonical_execution_source(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    _legacy, v2, legacy_id = _delegated(db_path)
    tasks = AutonomousTaskStore(db_path)
    claimed = tasks.claim_task(v2["task_id"], "worker")
    assert claimed
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE worker_tasks SET status='completed' WHERE id=?", (legacy_id,)
        )
    repaired = LegacyTaskReconciler(db_path).reconcile()
    assert repaired["repaired"] == 1
    assert _legacy_row(db_path, legacy_id)["status"] == "claimed"


def test_legacy_mirror_never_overrides_v2_truth(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    legacy, v2, legacy_id = _delegated(db_path)
    tasks = AutonomousTaskStore(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET max_attempts=1 WHERE task_id=?",
            (v2["task_id"],),
        )
    claimed = tasks.claim_task(v2["task_id"], "worker")
    assert claimed
    tasks.fail(v2["task_id"], "worker", claimed["lease_generation"], "real failure")
    assert not legacy.mirror_v2_terminal(
        legacy_id, v2["task_id"], "completed", {"false": "success"}, run_ref="run"
    )
    LegacyTaskReconciler(db_path).reconcile()
    assert _legacy_row(db_path, legacy_id)["status"] == "dead_letter"


def test_idempotent_migration_does_not_duplicate_effect(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    legacy, v2, legacy_id = _delegated(db_path, "legacy:stable")
    same = AutonomousTaskStore(db_path).enqueue(
        "pulse_check", {"value": 1}, idempotency_key="legacy:stable"
    )
    assert same["task_id"] == v2["task_id"]
    assert legacy.link_delegated_task(legacy_id, same["task_id"])
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM autonomous_tasks").fetchone()[0] == 1
