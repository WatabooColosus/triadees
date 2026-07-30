"""Monitor de duración wall-clock real para web, Ollama y SQLite."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psutil

from triade.runtime.task_leases import AutonomousTaskStore


def run_wall_clock_validation(
    *,
    duration_seconds: int,
    interval_seconds: int,
    db_path: str | Path,
    web_url: str,
    ollama_url: str,
) -> dict[str, Any]:
    if duration_seconds < 1 or interval_seconds < 1:
        raise ValueError("duration_and_interval_must_be_positive_real_seconds")
    started_wall = time.time()
    started = time.monotonic()
    baseline = _runtime_invariants(Path(db_path))
    baseline_task_ids = set(baseline.pop("task_ids"))
    baseline_recoveries = int(baseline["worker_restarts"])
    baseline_snapshot_bytes = _bytes_under(Path("artifacts/recovery"))
    baseline_rss_bytes = psutil.Process().memory_info().rss
    isolated_probe_start = _isolated_truth_probe()
    checks: list[dict[str, Any]] = []
    while True:
        now = time.monotonic()
        web_ok = _http_ok(web_url)
        ollama_ok = _http_ok(ollama_url)
        with sqlite3.connect(db_path, timeout=5) as conn:
            integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        invariants = _runtime_invariants(Path(db_path))
        current_task_ids = set(invariants.pop("task_ids"))
        checks.append(
            {
                "elapsed_seconds": round(now - started, 3),
                "web_ok": web_ok,
                "ollama_ok": ollama_ok,
                "db_integrity": integrity,
                **invariants,
                "lost_tasks": len(baseline_task_ids - current_task_ids),
            }
        )
        remaining = duration_seconds - (time.monotonic() - started)
        if remaining <= 0:
            break
        time.sleep(min(interval_seconds, remaining))
    elapsed = time.monotonic() - started
    passed = sum(
        item["web_ok"] and item["ollama_ok"] and item["db_integrity"] == "ok"
        for item in checks
    )
    availability = passed / len(checks)
    isolated_probe_end = _isolated_truth_probe()
    final = checks[-1]
    duplicate_effects = max(int(item["duplicate_effects"]) for item in checks)
    lost_tasks = max(int(item["lost_tasks"]) for item in checks)
    false_completed = max(int(item["false_completed"]) for item in checks)
    artifact_loss = max(int(item["artifact_loss"]) for item in checks)
    late_results_accepted = int(
        not (
            isolated_probe_start["late_result_rejected"]
            and isolated_probe_end["late_result_rejected"]
        )
    )
    rollback_success_percent = (
        100.0
        if isolated_probe_start["rollback_verified"]
        and isolated_probe_end["rollback_verified"]
        else 0.0
    )
    db_corruption = sum(item["db_integrity"] != "ok" for item in checks)
    metrics_passed = (
        duplicate_effects == 0
        and lost_tasks == 0
        and false_completed == 0
        and db_corruption == 0
        and late_results_accepted == 0
        and artifact_loss == 0
        and rollback_success_percent == 100.0
    )
    return {
        "requested_duration_seconds": duration_seconds,
        "elapsed_seconds": elapsed,
        "wall_clock_not_compressed": elapsed >= duration_seconds,
        "started_at_epoch": started_wall,
        "checks": checks,
        "availability": availability,
        "metrics": {
            "duplicate_effects": duplicate_effects,
            "lost_tasks": lost_tasks,
            "false_completed": false_completed,
            "db_corruption": db_corruption,
            "late_results_accepted": late_results_accepted,
            "artifact_loss": artifact_loss,
            "rollback_success_percent": rollback_success_percent,
            "worker_restarts": int(final["worker_restarts"]) - baseline_recoveries,
            "snapshot_growth_bytes": _bytes_under(Path("artifacts/recovery"))
            - baseline_snapshot_bytes,
            "resource_rss_growth_bytes": psutil.Process().memory_info().rss
            - baseline_rss_bytes,
        },
        "isolated_truth_probes": {
            "scope": "isolated_fencing_and_sqlite_rollback",
            "start": isolated_probe_start,
            "end": isolated_probe_end,
        },
        "passed": (
            elapsed >= duration_seconds and availability >= 0.99 and metrics_passed
        ),
    }


def write_report(report: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return 200 <= response.status < 300
    except OSError:
        return False


def _runtime_invariants(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path, timeout=5) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "autonomous_tasks" in tables:
            rows = list(
                conn.execute(
                    "SELECT task_id,idempotency_key,status,result_ref FROM autonomous_tasks"
                )
            )
        else:
            rows = []
        worker_restarts = (
            int(
                conn.execute(
                    "SELECT COUNT(*) FROM runtime_recovery_events "
                    "WHERE state='runtime_recovered'"
                ).fetchone()[0]
            )
            if "runtime_recovery_events" in tables
            else 0
        )
    idempotency_counts: dict[str, int] = {}
    false_completed = 0
    artifact_loss = 0
    for _task_id, idempotency_key, status, result_ref in rows:
        key = str(idempotency_key)
        idempotency_counts[key] = idempotency_counts.get(key, 0) + 1
        if str(status) == "completed" and (
            not result_ref or not Path(str(result_ref)).is_file()
        ):
            false_completed += 1
            artifact_loss += 1
    return {
        "task_ids": [str(row[0]) for row in rows],
        "duplicate_effects": sum(
            count - 1 for count in idempotency_counts.values() if count > 1
        ),
        "false_completed": false_completed,
        "artifact_loss": artifact_loss,
        "worker_restarts": worker_restarts,
    }


def _isolated_truth_probe() -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="triade-long-run-probe-") as directory:
        root = Path(directory)
        store = AutonomousTaskStore(root / "fencing.db")
        task = store.enqueue("probe", {}, idempotency_key="late-result-probe")
        claimed = store.claim_task(task["task_id"], "old-worker", lease_seconds=1)
        if not claimed:
            return {"late_result_rejected": False, "rollback_verified": False}
        generation = int(claimed["lease_generation"])
        with sqlite3.connect(root / "fencing.db") as conn:
            conn.execute(
                "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
                (
                    (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                    task["task_id"],
                ),
            )
        store.recover_expired()
        store.claim_task(task["task_id"], "new-worker", lease_seconds=10)
        late_result_rejected = not store.complete(
            task["task_id"], "old-worker", generation, "late"
        )

        rollback_db = root / "rollback.db"
        with sqlite3.connect(rollback_db) as conn:
            conn.execute("CREATE TABLE rollback_probe(value TEXT NOT NULL)")
            conn.execute("INSERT INTO rollback_probe VALUES('baseline')")
            conn.commit()
            conn.execute("BEGIN")
            conn.execute("UPDATE rollback_probe SET value='changed'")
            conn.rollback()
            value = str(conn.execute("SELECT value FROM rollback_probe").fetchone()[0])
        return {
            "late_result_rejected": late_result_rejected,
            "rollback_verified": value == "baseline",
        }


def _bytes_under(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
