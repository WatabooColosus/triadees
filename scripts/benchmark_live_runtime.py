"""Benchmark controlado del heartbeat local, sin inferencia ni red."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
from pathlib import Path

from triade.runtime.live_heartbeat import LiveHeartbeat


def percentile(values: list[float], percent: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percent)))
    return ordered[index]


def run(samples: int) -> dict[str, float | int]:
    with tempfile.TemporaryDirectory(prefix="triade-heartbeat-") as directory:
        heartbeat = LiveHeartbeat(Path(directory) / "benchmark.db")
        durations = [float(heartbeat.pulse()["duration_ms"]) for _ in range(samples)]
    return {
        "samples": samples,
        "p50_ms": percentile(durations, 0.50),
        "p95_ms": percentile(durations, 0.95),
        "p99_ms": percentile(durations, 0.99),
        "mean_ms": statistics.fmean(durations),
        "llm_invocations": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=200)
    args = parser.parse_args()
    print(json.dumps(run(max(1, args.samples)), indent=2))
