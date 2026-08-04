"""Casos reales del circuito canónico de tareas sobre SQLite temporal."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from triade.constitution.autonomy import authorize_task
from triade.runtime.governed_capability import GovernedFileWriteCapability
from triade.runtime.task_leases import MAX_DISPATCH_DEFERRALS, AutonomousTaskStore
from triade.workers.adaptive_scheduler import AdaptiveScheduler
from triade.workers.architecture import contract_for
from triade.workers.concurrency import ConcurrencySettings, RunningTaskRegistry
from triade.workers.task_queue import WorkerTaskQueue


def _store(tmp_path: Path) -> AutonomousTaskStore:
    return AutonomousTaskStore(tmp_path / "triade.db")


def _lease(store: AutonomousTaskStore, task_id: str, worker: str = "worker-1") -> dict:
    leased = store.claim_task(task_id, worker, lease_seconds=60)
    assert leased is not None
    return leased


def test_successful_task_queue_lease_effect_evidence_completion(tmp_path: Path) -> None:
    queue = WorkerTaskQueue(tmp_path / "triade.db")
    task = queue.enqueue("pulse_check", {"probe": "phase-4"}, run_ref="phase-4")
    leased = _lease(queue.canonical, str(task.id))
    generation = int(leased["lease_generation"])
    assert queue.canonical.start(str(task.id), "worker-1", generation)

    effect = tmp_path / "effect.json"
    effect.write_text('{"observed": true}', encoding="utf-8")
    assert queue.canonical.complete(str(task.id), "worker-1", generation, str(effect))
    completed = queue.canonical.get(str(task.id))
    assert completed and completed["status"] == "completed"
    assert completed["result_ref"] == str(effect)


def test_blocked_task_is_terminal_and_auditable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.enqueue("goal_install", {}, idempotency_key="blocked")
    leased = _lease(store, str(task["task_id"]))
    assert store.block(
        str(task["task_id"]),
        "worker-1",
        int(leased["lease_generation"]),
        "approval_required",
    )
    assert store.get(str(task["task_id"]))["status"] == "blocked"  # type: ignore[index]


def test_deferred_task_returns_to_queue_without_consuming_attempt(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="deferred")
    leased = _lease(store, str(task["task_id"]))
    assert store.defer_unstarted(
        str(task["task_id"]),
        "worker-1",
        int(leased["lease_generation"]),
        "concurrency:lane_limit",
        delay_seconds=0,
    )
    current = store.get(str(task["task_id"]))
    assert current and current["status"] == "deferred" and current["attempt"] == 0


def test_duplicate_idempotency_key_returns_same_task(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.enqueue("pulse_check", {"x": 1}, idempotency_key="same")
    second = store.enqueue("pulse_check", {"x": 1}, idempotency_key="same")
    assert first["task_id"] == second["task_id"]


def test_expired_lease_is_recovered_and_restart_can_claim_it(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="expired")
    leased = _lease(store, str(task["task_id"]), "worker-before-crash")
    assert store.start(
        str(task["task_id"]), "worker-before-crash", int(leased["lease_generation"])
    )
    expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
            (expired, task["task_id"]),
        )
    assert store.recover_expired() == [task["task_id"]]
    restarted = store.claim("worker-after-restart")
    assert restarted and restarted["task_id"] == task["task_id"]
    assert restarted["lease_generation"] > leased["lease_generation"]


def test_unknown_handler_and_undeclared_operation_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="worker task_type inválido"):
        WorkerTaskQueue(tmp_path / "triade.db").enqueue("unknown_handler")
    assert not authorize_task("unknown_handler").allowed
    with pytest.raises(ValueError, match="unknown_worker_task_type"):
        contract_for("unknown_handler")


def test_cooldown_prevents_immediate_reschedule(tmp_path: Path) -> None:
    scheduler = AdaptiveScheduler(tmp_path / "triade.db")
    assert not scheduler.should_skip_task("pulse_check")
    scheduler.record_task_execution("pulse_check", 5.0, True, run_ref="phase-4")
    assert scheduler.should_skip_task("pulse_check")


def test_repeated_dispatch_deferral_terminates_in_dead_letter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="livelock")
    task_id = str(task["task_id"])
    for _ in range(MAX_DISPATCH_DEFERRALS + 1):
        leased = _lease(store, task_id)
        assert store.defer_unstarted(
            task_id,
            "worker-1",
            int(leased["lease_generation"]),
            "concurrency:lane_limit",
            delay_seconds=0,
        )
        if store.get(task_id)["status"] == "dead_letter":  # type: ignore[index]
            break
    current = store.get(task_id)
    assert current and current["status"] == "dead_letter"
    assert current["last_error"] == "dispatch_livelock_guard"


def test_handler_failure_retries_then_dead_letters(tmp_path: Path) -> None:
    store = _store(tmp_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="failure", max_attempts=1)
    leased = _lease(store, str(task["task_id"]))
    result = store.fail(
        str(task["task_id"]),
        "worker-1",
        int(leased["lease_generation"]),
        "handler_failed",
    )
    assert result["status"] == "dead_letter"


def test_same_running_task_cannot_be_dispatched_twice() -> None:
    registry = RunningTaskRegistry(ConcurrencySettings.conservative())
    assert registry.try_admit("task-1", "pulse_check", {}).admitted
    duplicate = registry.try_admit("task-1", "pulse_check", {})
    assert not duplicate.admitted and duplicate.reason == "already_running"


def test_reversible_effect_restores_previous_state(tmp_path: Path) -> None:
    target = tmp_path / "result.txt"
    target.write_text("before", encoding="utf-8")
    capability = GovernedFileWriteCapability(target, "after", tmp_path / "evidence")
    capability.prepare()
    capability.execute()
    assert capability.verify().verified and target.read_text() == "after"
    capability.rollback()
    assert capability.verify_rollback().verified and target.read_text() == "before"
