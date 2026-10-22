#!/usr/bin/env python3
"""Tríade 5.8.0: non-invasive progress acceptance gate.

Do not use the unfinished worker_runs.summary_json while a daemon is running:
that summary is initialised at iterations=0 and finalised only on exit.
This gate requires evidence of real worker events or queue transitions.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def snap(script: Path, root: Path) -> dict:
    """Read one JSON diagnostic; the diagnostic does not modify SQLite."""
    proc = subprocess.run(
        [sys.executable, str(script), "--root", str(root)],
        capture_output=True, text=True, check=True,
    )
    report, _ = json.JSONDecoder().raw_decode(proc.stdout.lstrip())
    return report


def evaluate(before: dict, after: dict) -> dict:
    health = after.get("latest_health") or {}
    metrics = health.get("metrics") or {}
    worker = after.get("latest_worker") or {}
    old_progress = before.get("worker_progress") or {}
    new_progress = after.get("worker_progress") or {}

    def numeric(value, default=float("inf")):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default

    old_id = numeric(old_progress.get("last_event_id"), 0)
    new_id = numeric(new_progress.get("last_event_id"), 0)
    worker_event_advanced = (
        new_id > old_id and bool(new_progress.get("run_ref"))
        and new_progress.get("run_ref") == worker.get("run_ref")
    )
    old_transition = (before.get("latest_health") or {}).get("metrics", {}).get("last_task_transition_at")
    new_transition = metrics.get("last_task_transition_at")
    transition_advanced = bool(new_transition and new_transition != old_transition)
    completed_before = numeric((before.get("task_status") or {}).get("completed"), 0)
    completed_after = numeric((after.get("task_status") or {}).get("completed"), 0)
    completed_advanced = completed_after > completed_before

    checks = {
        "sqlite_ok": (after.get("checks") or {}).get("sqlite_integrity") == "ok",
        "health_snapshot_recent": numeric(health.get("snapshot_age_seconds")) < 45,
        "heartbeat_fresh": numeric(metrics.get("heartbeat_age_seconds")) < 45,
        "worker_running": worker.get("status") == "running",
        "health_not_stalled": health.get("state") not in (None, "stalled", "unhealthy"),
        "real_progress": worker_event_advanced or transition_advanced or completed_advanced,
    }
    return {
        "version": "5.8.0",
        "checks": checks,
        "pass": all(checks.values()),
        "observed_progress": {
            "worker_event_advanced": worker_event_advanced,
            "transition_advanced": transition_advanced,
            "completed_advanced": completed_advanced,
            "previous_worker_event_id": old_id,
            "current_worker_event_id": new_id,
            "worker_run_ref": worker.get("run_ref"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/content/Triade")
    parser.add_argument("--wait", type=int, default=30)
    parser.add_argument(
        "--script", default=str(Path(__file__).with_name("upgrade_triade_580.py"))
    )
    args = parser.parse_args()
    if args.wait < 1:
        parser.error("--wait must be positive")

    root = Path(args.root).resolve()
    script = Path(args.script).resolve()
    first = snap(script, root)
    time.sleep(args.wait)
    second = snap(script, root)
    verdict = evaluate(first, second)
    verdict["before"] = {
        "latest_health": first.get("latest_health"),
        "worker_progress": first.get("worker_progress"),
    }
    verdict["after"] = {
        "latest_health": second.get("latest_health"),
        "worker_progress": second.get("worker_progress"),
    }
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
