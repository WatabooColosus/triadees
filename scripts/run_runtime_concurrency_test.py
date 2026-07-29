#!/usr/bin/env python3
"""Real multiprocess contention test for the autonomous v2 queue."""

from __future__ import annotations

import argparse
import json
import multiprocessing
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from triade.runtime.task_artifacts import AtomicArtifactWriter
from triade.runtime.task_leases import AutonomousTaskStore


def _worker(db_path: str, artifacts_dir: str, worker_id: str) -> None:
    store = AutonomousTaskStore(db_path)
    while True:
        task = store.claim(worker_id, lease_seconds=5)
        if task is None:
            return
        task_id = str(task["task_id"])
        generation = int(task["lease_generation"])
        if not store.start(task_id, worker_id, generation):
            continue
        mode = str(task["payload"].get("mode") or "fast")
        if mode == "failed":
            store.fail(task_id, worker_id, generation, "injected_failure", base_delay_seconds=0)
            continue
        if mode == "timeout":
            store.mark_timeout(task_id, worker_id, generation, "injected_timeout", retryable=True)
            continue
        if mode == "slow":
            time.sleep(0.02)
            if not store.renew(task_id, worker_id, generation, lease_seconds=5):
                continue
        idempotency_key = str(task["idempotency_key"])
        with sqlite3.connect(db_path, timeout=10) as conn:
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute(
                "INSERT OR IGNORE INTO concurrency_effects(idempotency_key,task_id,worker_id) VALUES(?,?,?)",
                (idempotency_key, task_id, worker_id),
            )
        result_ref = Path(artifacts_dir) / task_id / "result.json"
        AtomicArtifactWriter.write_json(
            result_ref, {"task_id": task_id, "worker_id": worker_id, "effect": idempotency_key}
        )
        store.complete(task_id, worker_id, generation, str(result_ref))


def run_concurrency_validation(
    output_dir: str | Path, *, task_count: int = 100, worker_count: int = 3
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    db_path = output / "concurrency.db"
    artifacts = output / "artifacts"
    store = AutonomousTaskStore(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS concurrency_effects(
            idempotency_key TEXT PRIMARY KEY,task_id TEXT NOT NULL,worker_id TEXT NOT NULL)"""
        )
    started = time.monotonic()
    for index in range(task_count):
        mode = "failed" if index % 17 == 0 else "timeout" if index % 19 == 0 else "slow" if index % 7 == 0 else "fast"
        store.enqueue(
            "concurrency_probe", {"index": index, "mode": mode},
            idempotency_key=f"effect:{index}", priority=index % 10,
            max_attempts=1 if mode in {"failed", "timeout"} else 3,
        )
        if index % 10 == 0:
            duplicate = store.enqueue(
                "concurrency_probe", {"index": index, "mode": mode},
                idempotency_key=f"effect:{index}", priority=99,
            )
            assert duplicate["idempotency_key"] == f"effect:{index}"

    crash_task = store.enqueue(
        "concurrency_probe", {"mode": "fast", "crash_recovery": True},
        idempotency_key="effect:crash-recovery", priority=0,
    )
    crashed = store.claim_task(crash_task["task_id"], "killed-worker", lease_seconds=1)
    assert crashed
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), crash_task["task_id"]),
        )
    recovered = store.recover_expired()

    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(
            target=_worker, args=(str(db_path), str(artifacts), f"worker-{index}")
        )
        for index in range(worker_count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(60)
        if process.is_alive():
            process.terminate()
            process.join(5)
            raise RuntimeError("concurrency_worker_timeout")
        if process.exitcode != 0:
            raise RuntimeError(f"concurrency_worker_failed:{process.exitcode}")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        statuses = {
            str(row["status"]): int(row["count"])
            for row in conn.execute(
                "SELECT status,COUNT(*) AS count FROM autonomous_tasks GROUP BY status"
            )
        }
        total = int(conn.execute("SELECT COUNT(*) FROM autonomous_tasks").fetchone()[0])
        effects = int(conn.execute("SELECT COUNT(*) FROM concurrency_effects").fetchone()[0])
        duplicate_effects = int(conn.execute(
            "SELECT COUNT(*) FROM (SELECT idempotency_key FROM concurrency_effects GROUP BY idempotency_key HAVING COUNT(*)>1)"
        ).fetchone()[0])
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        missing_artifacts = int(conn.execute(
            "SELECT COUNT(*) FROM autonomous_tasks WHERE status='completed' AND result_ref IS NULL"
        ).fetchone()[0])
    terminal = statuses.get("completed", 0) + statuses.get("dead_letter", 0)
    report = {
        "task_rows": total,
        "enqueue_calls": task_count + (task_count + 9) // 10 + 1,
        "workers": worker_count,
        "statuses": statuses,
        "effects": effects,
        "duplicate_effects": duplicate_effects,
        "recovered_leases": len(recovered),
        "missing_artifacts": missing_artifacts,
        "db_integrity": integrity,
        "all_accounted": terminal == total,
        "elapsed_seconds": round(time.monotonic() - started, 6),
    }
    if duplicate_effects or missing_artifacts or integrity != "ok" or not report["all_accounted"]:
        raise AssertionError(json.dumps(report, sort_keys=True))
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="runs/concurrency-validation")
    parser.add_argument("--tasks", type=int, default=100)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--report")
    args = parser.parse_args()
    report = run_concurrency_validation(
        args.output_dir, task_count=max(1, args.tasks), worker_count=max(2, args.workers)
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
