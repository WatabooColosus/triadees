from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from triade.runtime.backpressure import (
    PressureSnapshot,
    QueueDrainBudget,
    RuntimeBackpressure,
)
from triade.runtime.live_heartbeat import LiveHeartbeat
from triade.runtime.resource_ledger import ResourceLedger
from triade.runtime.task_leases import AutonomousTaskStore


def test_queue_drain_has_task_limit() -> None:
    budget = QueueDrainBudget(max_tasks=2, max_seconds=30, per_type=10)
    budget.record("a")
    assert not budget.exhausted
    budget.record("b")
    assert budget.exhausted


def test_queue_drain_has_time_limit() -> None:
    budget = QueueDrainBudget(max_tasks=100, max_seconds=0.01, per_type=100)
    time.sleep(0.02)
    assert budget.exhausted


def test_heartbeat_runs_under_heavy_queue(tmp_path: Path) -> None:
    heartbeat = LiveHeartbeat(tmp_path / "runtime.db")
    budget = QueueDrainBudget(max_tasks=1, max_seconds=30, per_type=1)
    budget.record("heavy")
    pulse = heartbeat.pulse()
    assert budget.exhausted
    assert pulse["event"] == "heartbeat"
    assert pulse["llm_invocations"] == 0


def test_low_priority_tasks_are_not_starved(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(db_path)
    old = store.enqueue("old", {}, idempotency_key="old", priority=90)
    store.enqueue("new", {}, idempotency_key="new", priority=10)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET created_at=? WHERE task_id=?",
            ((datetime.now(UTC) - timedelta(minutes=200)).isoformat(), old["task_id"]),
        )
    claimed = store.claim("worker")
    assert claimed and claimed["task_id"] == old["task_id"]


def test_resource_pressure_defers_tasks(tmp_path: Path) -> None:
    ledger = ResourceLedger(tmp_path / "ledger.db")
    pressure = RuntimeBackpressure(
        ledger,
        probe=lambda: PressureSnapshot("degraded", ("memory_low",), 200, 5000, None),
    )
    assert not pressure.allows("goal_install", effectful=True)
    assert pressure.allows("pulse_check", effectful=False)


def test_disk_pressure_blocks_effectful_tasks(tmp_path: Path) -> None:
    ledger = ResourceLedger(tmp_path / "ledger.db")
    pressure = RuntimeBackpressure(
        ledger,
        probe=lambda: PressureSnapshot("critical", ("disk_critical",), 1000, 100, None),
    )
    assert not pressure.allows("goal_install", effectful=True)


def test_thermal_pressure_defers_gpu_work(tmp_path: Path) -> None:
    ledger = ResourceLedger(tmp_path / "ledger.db")
    pressure = RuntimeBackpressure(
        ledger,
        probe=lambda: PressureSnapshot("degraded", ("thermal_high",), 1000, 5000, 85),
    )
    assert not pressure.allows("goal_lora_train", effectful=True)


def test_per_type_quota_enables_fair_claim(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    store.enqueue("research", {"n": 1}, idempotency_key="r1", priority=1)
    store.enqueue("research", {"n": 2}, idempotency_key="r2", priority=1)
    maintenance = store.enqueue("maintenance", {}, idempotency_key="m", priority=50)
    first = store.claim("worker")
    assert first and first["task_type"] == "research"
    second = store.claim("worker", excluded_task_types={"research"})
    assert second and second["task_id"] == maintenance["task_id"]
