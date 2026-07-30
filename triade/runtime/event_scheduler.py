"""Planificador monotónico, dirigido por eventos y sin busy loop."""

from __future__ import annotations

import heapq
import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeAlias

Clock: TypeAlias = Callable[[], float]


@dataclass(order=True, slots=True)
class ScheduledJob:
    next_due_at: float
    priority: int
    name: str = field(compare=False)
    interval_seconds: float = field(compare=False)
    callback: Callable[[], Any] = field(compare=False)
    jitter_seconds: float = field(default=0.0, compare=False)
    enabled: bool = field(default=True, compare=False)
    run_count: int = field(default=0, compare=False)
    last_started_at: float | None = field(default=None, compare=False)
    last_duration_ms: float | None = field(default=None, compare=False)
    last_error: str | None = field(default=None, compare=False)


class EventDrivenScheduler:
    """Cola temporal segura que despierta por vencimiento o por evento externo."""

    def __init__(
        self,
        *,
        clock: Clock = time.monotonic,
        seed: int | None = None,
        wake_event: threading.Event | None = None,
    ) -> None:
        self._clock = clock
        self._random = random.Random(seed)
        self._jobs: list[ScheduledJob] = []
        self._by_name: dict[str, ScheduledJob] = {}
        self._lock = threading.RLock()
        self._wake_event = wake_event or threading.Event()

    def add_job(
        self,
        name: str,
        callback: Callable[[], Any],
        *,
        interval_seconds: float,
        priority: int = 50,
        jitter_seconds: float = 0.0,
        run_immediately: bool = False,
    ) -> ScheduledJob:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        now = self._clock()
        due = (
            now
            if run_immediately
            else now + self._jittered(interval_seconds, jitter_seconds)
        )
        job = ScheduledJob(
            due, priority, name, interval_seconds, callback, jitter_seconds
        )
        with self._lock:
            if name in self._by_name:
                raise ValueError(f"job already registered: {name}")
            self._by_name[name] = job
            heapq.heappush(self._jobs, job)
            self._wake_event.set()
        return job

    def get_due_jobs(self, now: float | None = None) -> list[ScheduledJob]:
        current = self._clock() if now is None else now
        due: list[ScheduledJob] = []
        with self._lock:
            while self._jobs and self._jobs[0].next_due_at <= current:
                job = heapq.heappop(self._jobs)
                if job.enabled:
                    due.append(job)
        return sorted(due, key=lambda item: item.priority)

    def execute_due(self, now: float | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for job in self.get_due_jobs(now):
            started = self._clock()
            job.last_started_at = started
            try:
                value = job.callback()
                job.last_error = None
                results.append({"name": job.name, "status": "ok", "result": value})
            except (
                OSError,
                ImportError,
                RuntimeError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
            ) as exc:
                job.last_error = str(exc)
                results.append({"name": job.name, "status": "error", "error": str(exc)})
            finally:
                finished = self._clock()
                job.run_count += 1
                job.last_duration_ms = max(0.0, (finished - started) * 1000.0)
                job.next_due_at = finished + self._jittered(
                    job.interval_seconds, job.jitter_seconds
                )
                with self._lock:
                    if job.enabled:
                        heapq.heappush(self._jobs, job)
        return results

    def next_due_time(self) -> float | None:
        with self._lock:
            return self._jobs[0].next_due_at if self._jobs else None

    def calculate_wait(self, *, maximum_seconds: float = 60.0) -> float:
        due = self.next_due_time()
        if due is None:
            return maximum_seconds
        return max(0.0, min(maximum_seconds, due - self._clock()))

    def wait(
        self,
        *,
        shutdown_event: threading.Event | None = None,
        maximum_seconds: float = 60.0,
    ) -> str:
        if shutdown_event is not None and shutdown_event.is_set():
            return "shutdown"
        self._wake_event.clear()
        timeout = self.calculate_wait(maximum_seconds=maximum_seconds)
        self._wake_event.wait(timeout=timeout)
        if shutdown_event is not None and shutdown_event.is_set():
            return "shutdown"
        return "event" if self._wake_event.is_set() else "due"

    def wake(self) -> None:
        self._wake_event.set()

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            jobs = list(self._by_name.values())
        return {
            "state": "active",
            "clock": "monotonic",
            "job_count": len(jobs),
            "next_due_ms": min(
                (max(0.0, job.next_due_at - now) * 1000 for job in jobs), default=None
            ),
            "jobs": {
                job.name: {
                    "next_due_ms": max(0.0, (job.next_due_at - now) * 1000),
                    "run_count": job.run_count,
                    "last_duration_ms": job.last_duration_ms,
                    "last_error": job.last_error,
                }
                for job in jobs
            },
        }

    def _jittered(self, interval: float, jitter: float) -> float:
        if jitter <= 0:
            return interval
        return max(0.001, interval + self._random.uniform(-jitter, jitter))
