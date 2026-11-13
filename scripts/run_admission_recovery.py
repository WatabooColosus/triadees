"""Crash a real leased WorkerLoop after an observed file effect, then recover.

Fault injection and restart supervision belong to this bounded verification
driver. The handlers, leases, fencing, receipts and rollback are normal runtime
components. Only this experiment's processes and files are targeted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psutil

from triade.db import sqlite3
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop

ROOT = Path(__file__).resolve().parents[1]
TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-case", type=Path)
    args = parser.parse_args()
    if args.worker_case:
        case = args.worker_case.resolve()
        if not case.is_relative_to(ROOT / "artifacts/evolution"):
            raise ValueError("case_outside_authorized_scope")
        config = json.loads(case.read_text())
        db, work = Path(config["db"]).resolve(), case.parent
        if not db.is_relative_to(ROOT / "artifacts/evolution"):
            raise ValueError("database_outside_authorized_scope")
        loop = WorkerLoop(
            db_path=db,
            runs_dir=work / "runs",
            lock_file=work / "worker.lock",
            stop_file=work / "worker.stop",
        )
        actor = f"recovery-worker:{os.getpid()}"
        lease = loop.autonomous_tasks.claim_task(
            config["task_id"], actor, lease_seconds=60
        )
        if lease is None:
            raise RuntimeError("recovery_task_not_claimable")
        outcome = loop._execute_autonomous_task(
            lease,
            actor,
            work / "runs",
            WorkerRunConfig(task_timeout=15, concurrency_enabled=False),
            {"tasks_completed": 0, "tasks_blocked": 0, "errors": []},
        )
        (work / f"worker-{os.getpid()}-outcome.json").write_text(
            json.dumps(outcome, ensure_ascii=True), encoding="utf-8"
        )
        return (
            0
            if loop.autonomous_tasks.get(config["task_id"])["status"] == "completed"
            else 1
        )
    prior = json.loads(
        (ROOT / "reports/evolution/productive_learning_chain_v3.json").read_text(
            encoding="utf-8"
        )
    )
    owner = Path(prior["artifact_ref"]).resolve()
    if not owner.is_relative_to(ROOT / "artifacts/evolution"):
        raise ValueError("experiment_outside_authorized_scope")
    work = owner / ("recovery-" + uuid4().hex[:12])
    work.mkdir()
    db, target = owner / "learning.db", work / "configuration.json"
    certificate = json.loads(
        (ROOT / "reports/evolution/admission_certification_latest.json").read_text(
            encoding="utf-8"
        )
    )
    baseline = json.loads(
        certificate["outcome"]["training"]["arms"]["treatment"][0]["response"]
    )["expression"]
    target.write_text(json.dumps({"expression": baseline}), encoding="utf-8")
    original = target.read_bytes()
    content = json.dumps({"expression": "0", "padding": "x" * (4 * 1024**2)})
    loop = WorkerLoop(
        db_path=db,
        runs_dir=work / "runs",
        lock_file=work / "worker.lock",
        stop_file=work / "worker.stop",
    )
    task = loop.autonomous_tasks.enqueue(
        "write_governed_text_artifact",
        {
            "target": str(target),
            "content": content,
            "authorized_root": str(work),
            "correlation_id": prior["correlation_id"],
        },
        idempotency_key=work.name,
        max_attempts=3,
    )
    case = work / "case.json"
    case.write_text(
        json.dumps({"db": str(db), "task_id": task["task_id"]}), encoding="utf-8"
    )
    command = [
        sys.executable,
        "-m",
        "scripts.run_admission_recovery",
        "--worker-case",
        str(case),
    ]
    log = (work / "workers.log").open("w", encoding="utf-8")
    first = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    original_mtime, crash = target.stat().st_mtime_ns, None
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline and first.poll() is None:
        if target.stat().st_mtime_ns != original_mtime:
            with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
                row = conn.execute(
                    "SELECT status,lease_generation,worker_id,lease_expires_at FROM autonomous_tasks WHERE task_id=?",
                    (task["task_id"],),
                ).fetchone()
            if row[0] == "running":
                process = psutil.Process(first.pid)
                if (
                    not any(
                        "scripts.run_admission_recovery" in arg
                        for arg in process.cmdline()
                    )
                    or Path(process.cwd()).resolve() != ROOT
                ):
                    raise RuntimeError("crash_process_scope_mismatch")
                children = [
                    (child.pid, child.create_time())
                    for child in process.children(recursive=True)
                ]
                crash = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "pid": first.pid,
                    "lease_generation": row[1],
                    "worker_id": row[2],
                    "lease_expires_at": row[3],
                    "target_mtime_ns": target.stat().st_mtime_ns,
                    "children": children,
                }
                process.kill()
                first.wait(timeout=10)
                for pid, created in children:
                    try:
                        child = psutil.Process(pid)
                        if child.create_time() == created:
                            child.kill()
                    except psutil.NoSuchProcess:
                        pass
                break
        time.sleep(0.002)
    if crash is None:
        first.wait(timeout=45)
        log.close()
        result = {
            "truth": False,
            "reason": "did_not_observe_running_task_after_effect",
            "task_id": task["task_id"],
            "worker_exit": first.returncode,
            "artifact_ref": str(work),
        }
        (ROOT / "reports/evolution/admission_recovery_latest.json").write_text(
            json.dumps(result, indent=2)
        )
        print(json.dumps(result))
        return 1
    recovery_started = time.monotonic()
    deadline = time.monotonic() + 100
    recovered = []
    while time.monotonic() < deadline:
        recovered = loop.autonomous_tasks.recover_expired()
        if task["task_id"] in recovered:
            break
        time.sleep(1)
    if task["task_id"] not in recovered:
        raise RuntimeError("lease_recovery_not_observed")
    second = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    second.wait(timeout=60)
    log.close()
    final = loop.autonomous_tasks.get(task["task_id"])
    outcome = json.loads((work / f"worker-{second.pid}-outcome.json").read_text())
    with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    replay = outcome.get("execution", {}).get("idempotent_replay")
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tested_source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "task_id": task["task_id"],
        "correlation_id": prior["correlation_id"],
        "crash": crash,
        "pid_after": second.pid,
        "lease_generation_after": final["lease_generation"],
        "recovery_seconds": time.monotonic() - recovery_started,
        "final_status": final["status"],
        "db_integrity": integrity,
        "idempotent_replay": replay,
        "duplicate_effects": 0
        if replay and target.stat().st_mtime_ns == crash["target_mtime_ns"]
        else None,
        "lost_tasks": 0 if final["status"] == "completed" else 1,
        "artifact_ref": str(work),
        "rollback_spec": outcome.get("rollback_spec"),
        "baseline_sha256": hashlib.sha256(original).hexdigest(),
        "scope": "Real normal WorkerLoop task crash/replay in existing experiment DB; restart supervised by this verification driver, not deployed Windows supervisor",
        "truth": second.returncode == 0
        and final["status"] == "completed"
        and replay
        and integrity == "ok"
        and target.stat().st_mtime_ns == crash["target_mtime_ns"],
    }
    (ROOT / "reports/evolution/admission_recovery_latest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "truth",
                    "final_status",
                    "duplicate_effects",
                    "lost_tasks",
                    "recovery_seconds",
                )
            }
        )
    )
    return 0 if result["truth"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
