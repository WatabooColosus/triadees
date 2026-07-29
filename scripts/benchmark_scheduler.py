"""Benchmark de despacho monotónico acelerado."""

from __future__ import annotations

import argparse
import json
import time

from triade.runtime.event_scheduler import EventDrivenScheduler


class Clock:
    value = 0.0

    def __call__(self) -> float:
        return self.value


def run(logical_hours: int) -> dict[str, float | int]:
    clock = Clock()
    scheduler = EventDrivenScheduler(clock=clock, seed=1)
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
    started = time.perf_counter()
    for second in range(logical_hours * 3600 + 1):
        clock.value = float(second)
        scheduler.execute_due()
    elapsed = time.perf_counter() - started
    return {
        "logical_hours": logical_hours,
        **counts,
        "wall_seconds": elapsed,
        "job_count": scheduler.snapshot()["job_count"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--logical-hours", type=int, default=24)
    args = parser.parse_args()
    print(json.dumps(run(max(1, args.logical_hours)), indent=2))
