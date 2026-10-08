from __future__ import annotations

import threading
import time
import sqlite3
import pytest

from triade.runtime.event_scheduler import EventDrivenScheduler
from triade.runtime.live_heartbeat import LiveHeartbeat
from triade.runtime.wake_bus import runtime_wake_event
from triade.workers.task_queue import WorkerTaskQueue


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_real_sqlite_contention_defers_job_without_losing_other_due_work(tmp_path):
    path = tmp_path / "contended.db"
    owner = sqlite3.connect(path)
    owner.execute("CREATE TABLE pulses(value INTEGER)")
    owner.commit()
    owner.execute("BEGIN IMMEDIATE")
    clock = FakeClock()
    scheduler = EventDrivenScheduler(clock=clock)
    calls = []
    def write():
        connection = sqlite3.connect(path, timeout=0)
        try:
            connection.execute("INSERT INTO pulses VALUES (1)")
            connection.commit()
        finally:
            connection.close()
    scheduler.add_job("pulse", write, interval_seconds=5, priority=0, run_immediately=True)
    scheduler.add_job("other", lambda: calls.append("ran"), interval_seconds=5, run_immediately=True)
    try:
        results = scheduler.execute_due()
        assert results[0]["status"] == "retry_pending"
        assert calls == ["ran"]
        assert scheduler.snapshot()["jobs"]["pulse"]["last_error"]
        owner.rollback()
        clock.now += 5
        assert scheduler.execute_due()[0]["status"] == "ok"
        assert owner.execute("SELECT count(*) FROM pulses").fetchone()[0] == 1
    finally:
        owner.close()


def test_scheduler_does_not_hide_non_contention_database_faults(tmp_path):
    scheduler = EventDrivenScheduler()
    def invalid_query():
        with sqlite3.connect(tmp_path / "invalid.db") as connection:
            connection.execute("SELECT * FROM absent_table")
    scheduler.add_job("invalid", invalid_query, interval_seconds=5, run_immediately=True)
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        scheduler.execute_due()


def test_scheduler_uses_monotonic_due_times_without_drift() -> None:
    clock = FakeClock()
    calls: list[float] = []
    scheduler = EventDrivenScheduler(clock=clock, seed=1)
    scheduler.add_job(
        "heartbeat",
        lambda: calls.append(clock()),
        interval_seconds=5,
        run_immediately=True,
    )

    scheduler.execute_due()
    assert calls == [100.0]
    assert scheduler.calculate_wait() == 5.0

    clock.now = 105.0
    scheduler.execute_due()
    assert calls == [100.0, 105.0]
    assert scheduler.snapshot()["clock"] == "monotonic"


def test_scheduler_jitter_stays_bounded() -> None:
    clock = FakeClock()
    scheduler = EventDrivenScheduler(clock=clock, seed=7)
    job = scheduler.add_job(
        "health", lambda: None, interval_seconds=15, jitter_seconds=2
    )
    assert 113.0 <= job.next_due_at <= 117.0


def test_new_task_wakes_idle_runtime(tmp_path) -> None:
    db_path = tmp_path / "runtime.db"
    event = runtime_wake_event(db_path)
    event.clear()
    scheduler = EventDrivenScheduler(wake_event=event)
    scheduler.add_job("later", lambda: None, interval_seconds=60)
    result: list[str] = []

    waiter = threading.Thread(
        target=lambda: result.append(scheduler.wait(maximum_seconds=2))
    )
    waiter.start()
    time.sleep(0.02)
    WorkerTaskQueue(db_path).enqueue("pulse_check", {"wake": True})
    waiter.join(timeout=1)

    assert result == ["event"]


def test_heartbeat_is_lightweight_and_declares_no_llm(tmp_path) -> None:
    heartbeat = LiveHeartbeat(tmp_path / "runtime.db")
    durations = [heartbeat.pulse()["duration_ms"] for _ in range(10)]
    snapshot = heartbeat.snapshot()

    assert snapshot["status"] == "healthy"
    assert snapshot["cycle"] == 10
    assert snapshot["llm_invocations"] == 0
    assert max(durations) < 500
    assert sum(durations) / len(durations) < 150


def test_accelerated_day_has_bounded_scheduler_state() -> None:
    clock = FakeClock()
    scheduler = EventDrivenScheduler(clock=clock, seed=3)
    counts = {"heartbeat": 0, "dispatch": 0}
    scheduler.add_job(
        "heartbeat",
        lambda: counts.__setitem__("heartbeat", counts["heartbeat"] + 1),
        interval_seconds=5,
        run_immediately=True,
    )
    scheduler.add_job(
        "dispatch",
        lambda: counts.__setitem__("dispatch", counts["dispatch"] + 1),
        interval_seconds=20,
        run_immediately=True,
    )

    for second in range(86_401):
        clock.now = 100.0 + second
        scheduler.execute_due()

    snapshot = scheduler.snapshot()
    assert snapshot["job_count"] == 2
    assert counts["heartbeat"] == 17_281
    assert counts["dispatch"] == 4_321
    assert snapshot["next_due_ms"] >= 0


def test_recreated_heartbeat_does_not_reset_shared_counter(tmp_path):
    db = tmp_path / "runtime.db"
    worker = LiveHeartbeat(db)
    assert worker.pulse()["cycle"] == 1
    assert worker.pulse()["cycle"] == 2
    assert LiveHeartbeat(db).pulse()["cycle"] == 3
    assert worker.pulse()["cycle"] == 4


def test_concurrent_heartbeat_instances_increment_atomically(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    db = tmp_path / "runtime.db"
    instances = [LiveHeartbeat(db) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: instances[n % 4].pulse(), range(40)))
    assert LiveHeartbeat(db).snapshot()["cycle"] == 40
    assert {r["cycle"] for r in results} == set(range(1, 41))
