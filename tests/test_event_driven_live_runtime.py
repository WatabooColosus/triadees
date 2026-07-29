from __future__ import annotations

import threading
import time

from triade.runtime.event_scheduler import EventDrivenScheduler
from triade.runtime.live_heartbeat import LiveHeartbeat
from triade.runtime.wake_bus import runtime_wake_event
from triade.workers.task_queue import WorkerTaskQueue


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_scheduler_uses_monotonic_due_times_without_drift() -> None:
    clock = FakeClock()
    calls: list[float] = []
    scheduler = EventDrivenScheduler(clock=clock, seed=1)
    scheduler.add_job("heartbeat", lambda: calls.append(clock()), interval_seconds=5, run_immediately=True)

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
    job = scheduler.add_job("health", lambda: None, interval_seconds=15, jitter_seconds=2)
    assert 113.0 <= job.next_due_at <= 117.0


def test_new_task_wakes_idle_runtime(tmp_path) -> None:
    db_path = tmp_path / "runtime.db"
    event = runtime_wake_event(db_path)
    event.clear()
    scheduler = EventDrivenScheduler(wake_event=event)
    scheduler.add_job("later", lambda: None, interval_seconds=60)
    result: list[str] = []

    waiter = threading.Thread(target=lambda: result.append(scheduler.wait(maximum_seconds=2)))
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
        "heartbeat", lambda: counts.__setitem__("heartbeat", counts["heartbeat"] + 1),
        interval_seconds=5, run_immediately=True,
    )
    scheduler.add_job(
        "dispatch", lambda: counts.__setitem__("dispatch", counts["dispatch"] + 1),
        interval_seconds=20, run_immediately=True,
    )

    for second in range(86_401):
        clock.now = 100.0 + second
        scheduler.execute_due()

    snapshot = scheduler.snapshot()
    assert snapshot["job_count"] == 2
    assert counts["heartbeat"] == 17_281
    assert counts["dispatch"] == 4_321
    assert snapshot["next_due_ms"] >= 0
