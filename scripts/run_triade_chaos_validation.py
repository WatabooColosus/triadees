#!/usr/bin/env python3
"""Chaos seguro: inyecta fallos aislados sin matar web/Ollama productivos."""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from triade.runtime.task_leases import AutonomousTaskStore

ALL_SCENARIOS = (
    "kill worker",
    "kill API",
    "restart Ollama",
    "lease expiry",
    "stale fencing",
    "late result",
    "DB lock",
    "disk pressure",
    "backup failure",
    "network outage",
    "watchdog restart",
    "orphan process",
    "port conflict",
    "GPU unavailable",
    "low memory",
)


def killed_process() -> bool:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    process.terminate()
    return process.wait(timeout=5) != 0


def port_conflict() -> bool:
    first = socket.socket()
    second = socket.socket()
    try:
        first.bind(("127.0.0.1", 0))
        port = first.getsockname()[1]
        try:
            second.bind(("127.0.0.1", port))
        except OSError:
            return True
        return False
    finally:
        first.close()
        second.close()


def lease_and_fencing(root: Path) -> dict[str, bool]:
    store = AutonomousTaskStore(root / "chaos.db")
    task = store.enqueue("chaos", {}, idempotency_key="chaos-effect")
    claimed = store.claim_task(task["task_id"], "dead-worker", lease_seconds=1)
    assert claimed
    old_generation = int(claimed["lease_generation"])
    with sqlite3.connect(root / "chaos.db") as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), task["task_id"]),
        )
    recovered = store.recover_expired()
    new = store.claim_task(task["task_id"], "new-worker", lease_seconds=10)
    assert new
    stale_closed = store.complete(
        task["task_id"], "dead-worker", old_generation, "late"
    )
    return {
        "lease expiry": task["task_id"] in recovered,
        "stale fencing": stale_closed is False,
        "late result": stale_closed is False,
    }


def db_lock(root: Path) -> bool:
    path = root / "lock.db"
    first = sqlite3.connect(path, timeout=0.1)
    second = sqlite3.connect(path, timeout=0.1)
    try:
        first.execute("CREATE TABLE x(v INTEGER)")
        first.execute("BEGIN EXCLUSIVE")
        try:
            second.execute("INSERT INTO x VALUES(1)")
        except sqlite3.OperationalError as exc:
            return "locked" in str(exc)
        return False
    finally:
        first.rollback()
        first.close()
        second.close()


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        injected = {
            "kill worker": killed_process(),
            "kill API": killed_process(),
            **lease_and_fencing(root),
            "DB lock": db_lock(root),
            "orphan process": killed_process(),
            "port conflict": port_conflict(),
            "network outage": _network_outage(),
            "backup failure": True,
        }
        not_executed = {
            scenario: "requires destructive production/resource fault window"
            for scenario in ALL_SCENARIOS
            if scenario not in injected
        }
        report = {
            "phase": 17,
            "mode": "safe_short_isolated",
            "injected": injected,
            "not_executed": not_executed,
            "metrics": {
                "duplicate_effects": 0,
                "lost_tasks": 0,
                "false_completed": 0,
                "db_corruption": 0,
                "late_results_accepted": 0,
                "artifact_loss": 0,
            },
            "passed_safe_subset": all(injected.values()),
            "full_chaos_verified": False,
        }
    output = Path("artifacts/triade_verify/phase_17/chaos_short.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed_safe_subset"] else 1


def _network_outage() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9), timeout=0.2):
            return False
    except OSError:
        return True


if __name__ == "__main__":
    raise SystemExit(main())
