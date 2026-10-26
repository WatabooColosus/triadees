"""Kill a real isolated worker after its effect commits, recover its lease.

Uses the actual queue, fencing and artifact writer. No production DB writes.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sqlite3
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from triade.runtime.task_artifacts import AtomicArtifactWriter
from triade.runtime.task_leases import AutonomousTaskStore

ROOT = Path(__file__).resolve().parents[1]


def worker(root):
    root = Path(root)
    db = root / "recovery.db"
    store = AutonomousTaskStore(db)
    deadline = time.monotonic() + 25
    task = None
    while task is None and time.monotonic() < deadline:
        store.recover_expired()
        task = store.claim(f"process-{os.getpid()}", lease_seconds=2)
        if task is None:
            time.sleep(0.2)
    if task is None:
        raise RuntimeError("task not recovered")
    owner = task["worker_id"]
    generation = task["lease_generation"]
    tid = task["task_id"]
    if not store.start(tid, owner, generation):
        raise RuntimeError("start fencing failed")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO effects(effect_id, task_id, value) VALUES(?,?,?)",
            (task["idempotency_key"], tid, sum(task["payload"]["values"])),
        )
    AtomicArtifactWriter.write_json(
        root / f"checkpoint-{task['attempt']}.json",
        {
            "pid": os.getpid(),
            "task_id": tid,
            "lease_generation": generation,
            "attempt": task["attempt"],
            "effect_id": task["idempotency_key"],
        },
    )
    if task["attempt"] == 1:
        time.sleep(300)  # deliberate crash window, effect already persisted
    ref = root / "receipt.json"
    AtomicArtifactWriter.write_json(
        ref,
        {
            "task_id": tid,
            "actor": owner,
            "lease_generation": generation,
            "effect_id": task["idempotency_key"],
            "result": sum(task["payload"]["values"]),
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
    if not store.complete(tid, owner, generation, str(ref)):
        raise RuntimeError("completion fencing failed")


def supervise(root):
    for attempt in range(2):
        child = mp.Process(target=worker, args=(root,))
        child.start()
        child.join(45)
        if child.is_alive():
            child.terminate()
            child.join()
            raise RuntimeError("worker timeout")
        if child.exitcode == 0:
            return
        time.sleep(0.3)
    raise RuntimeError("restart budget exhausted")


def run(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    db = root / "recovery.db"
    store = AutonomousTaskStore(db)
    with sqlite3.connect(db) as c:
        c.execute(
            "CREATE TABLE effects(effect_id TEXT PRIMARY KEY,task_id TEXT,value INTEGER)"
        )
    task = store.enqueue(
        "receipt_probe",
        {"values": [11, 29, 7]},
        idempotency_key="sum-recovery-47",
        max_attempts=3,
    )
    supervisor = mp.Process(target=supervise, args=(str(root),))
    supervisor.start()
    deadline = time.monotonic() + 30
    marker = root / "checkpoint-1.json"
    try:
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not marker.exists():
            raise RuntimeError("worker never reached persisted checkpoint")
        first = json.loads(marker.read_text())
        before = store.get(task["task_id"])
        child = psutil.Process(first["pid"])
        if child.ppid() != supervisor.pid:
            raise RuntimeError("refusing to kill unowned process")
        start = time.monotonic()
        child.terminate()
        supervisor.join(40)
        if supervisor.is_alive():
            raise RuntimeError("automatic recovery timed out")
        elapsed = time.monotonic() - start
        after = store.get(task["task_id"])
        second = json.loads((root / "checkpoint-2.json").read_text())
        with sqlite3.connect(db) as c:
            effects = c.execute("SELECT effect_id,value FROM effects").fetchall()
            integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
        receipt = json.loads((root / "receipt.json").read_text())
        truth = (
            supervisor.exitcode == 0
            and after["status"] == "completed"
            and effects == [("sum-recovery-47", 47)]
            and integrity == "ok"
            and second["lease_generation"] > first["lease_generation"]
            and receipt["task_id"] == task["task_id"]
        )
        return {
            "git_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "timestamp": datetime.now(UTC).isoformat(),
            "scope": "Real isolated worker crash with production queue/fencing/artifact code; separate API restart observation required",
            "pid_before": first["pid"],
            "pid_after": second["pid"],
            "task_id": task["task_id"],
            "lease_before": before,
            "lease_after": after,
            "effect_id": effects[0][0] if effects else None,
            "duplicate_effects": max(0, len(effects) - 1),
            "effect_result": effects,
            "db_integrity": integrity,
            "recovery_seconds": elapsed,
            "final_task_status": after["status"],
            "automatic_recovery": True,
            "truth": truth,
            "receipt": receipt,
            "production_writes": False,
        }
    finally:
        if supervisor.is_alive():
            for child in psutil.Process(supervisor.pid).children(recursive=True):
                child.terminate()
            supervisor.terminate()
            supervisor.join()


def main():
    result = run(ROOT / "artifacts/level8" / f"task-recovery-{time.time_ns()}")
    from scripts.run_level8_soak import bind_report

    bind_report(result)
    (ROOT / "reports/level8/recovery_task_inflight.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "truth",
                    "recovery_seconds",
                    "duplicate_effects",
                    "final_task_status",
                ]
            }
        )
    )
    return 0 if result["truth"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
