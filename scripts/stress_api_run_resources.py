#!/usr/bin/env python3
"""Bounded `/api/run` stress with process/SQLite resource evidence."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import psutil


def _service_pid() -> int:
    result = subprocess.run(
        ["systemctl", "show", "-p", "MainPID", "--value", "triade-api.service"],
        check=True,
        capture_output=True,
        text=True,
    )
    pid = int(result.stdout.strip())
    if pid <= 0:
        raise RuntimeError("triade-api.service has no live MainPID")
    return pid


def _sample(process: psutil.Process, database: Path) -> dict[str, float | int]:
    database_path = str(database.resolve())
    sqlite_fds = sum(
        opened.path == database_path or opened.path.startswith(f"{database_path}-")
        for opened in process.open_files()
    )
    return {
        "rss_mb": round(process.memory_info().rss / (1024 * 1024), 2),
        "fd_total": process.num_fds(),
        "sqlite_fds": sqlite_fds,
    }


def _run(url: str, index: int, timeout: float) -> dict[str, Any]:
    payload = json.dumps(
        {
            "text": f"Resource lifecycle verification run {index}",
            "source": "resource_stress",
            "use_ollama": False,
        }
    ).encode()
    request = urllib.request.Request(
        f"{url}/api/run",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            return {
                "ok": response.status == 200,
                "status": response.status,
                "latency_seconds": time.monotonic() - started,
            }
    except Exception as exc:  # noqa: BLE001 - every request failure is evidence
        return {
            "ok": False,
            "error": type(exc).__name__,
            "latency_seconds": time.monotonic() - started,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=int)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--database", default="triade/memory/triade.db")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--cooldown", type=float, default=10)
    args = parser.parse_args()

    process = psutil.Process(_service_pid())
    database = Path(args.database)
    before = _sample(process, database)
    samples = [before]
    stop = threading.Event()

    def monitor() -> None:
        while not stop.wait(0.1):
            try:
                samples.append(_sample(process, database))
            except (psutil.Error, OSError):
                return

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(args.concurrency, args.runs)
    ) as executor:
        results = list(
            executor.map(
                lambda index: _run(args.url, index, args.timeout), range(args.runs)
            )
        )
    duration = time.monotonic() - started
    stop.set()
    monitor_thread.join()
    peak = {
        key: max(sample[key] for sample in samples)
        for key in ("rss_mb", "fd_total", "sqlite_fds")
    }
    time.sleep(args.cooldown)
    after = _sample(process, database)
    latencies = [float(result["latency_seconds"]) for result in results]
    report = {
        "runs": args.runs,
        "concurrency": min(args.concurrency, args.runs),
        "duration_seconds": round(duration, 3),
        "failures": sum(not result["ok"] for result in results),
        "latency_seconds": {
            "min": round(min(latencies), 3),
            "median": round(statistics.median(latencies), 3),
            "max": round(max(latencies), 3),
        },
        "before": before,
        "peak": peak,
        "after": after,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return int(report["failures"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
