"""Verify normal distribution and education workers after certified admission."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from triade.db import sqlite3
from triade.workers.contracts import WorkerRunConfig
from triade.workers.mission_planner import MissionPlanner
from triade.workers.worker_loop import WorkerLoop

ROOT = Path(__file__).resolve().parents[1]
TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--applications", type=int, choices=range(1, 6), default=1)
    count = parser.parse_args().applications
    os.environ.setdefault("TRIADE_NEURAL_LEARNING_ROUTING", "1")
    previous = json.loads(
        (ROOT / "reports/evolution/productive_learning_chain_v3.json").read_text(
            encoding="utf-8"
        )
    )
    certification = json.loads(
        (ROOT / "reports/evolution/admission_certification_latest.json").read_text(
            encoding="utf-8"
        )
    )
    if not certification.get("truth"):
        raise RuntimeError("certified_admission_required")
    work = Path(previous["artifact_ref"]).resolve()
    if not work.is_relative_to(ROOT / "artifacts/evolution"):
        raise ValueError("experiment_outside_authorized_scope")
    cid, correlation = previous["candidate_id"], certification["correlation_id"]
    loop = WorkerLoop(
        db_path=work / "learning.db",
        runs_dir=work / "runs",
        lock_file=work / "application.lock",
        stop_file=work / "application.stop",
    )
    planned = MissionPlanner(
        db_path=work / "learning.db"
    )._plan_neural_learning_distribution()
    route = next(
        (item for item in planned if item.payload.get("candidate_id") == cid), None
    )

    def execute(task_type, payload, key):
        task = loop.autonomous_tasks.enqueue(
            task_type, payload, idempotency_key=key, max_attempts=1
        )
        lease = loop.autonomous_tasks.claim_task(
            task["task_id"], correlation, lease_seconds=240
        )
        if lease is None:
            raise RuntimeError("verification_task_not_claimable")
        outcome = loop._execute_autonomous_task(
            lease,
            correlation,
            work / "runs",
            WorkerRunConfig(task_timeout=180, concurrency_enabled=False),
            {"tasks_completed": 0, "tasks_blocked": 0, "errors": []},
        )
        return {"task": loop.autonomous_tasks.get(task["task_id"]), "outcome": outcome}

    distribution = (
        execute(route.task_type, route.payload, f"certified-route:{cid}")
        if route
        else None
    )
    with sqlite3.connect(work / "learning.db") as conn:
        before = conn.execute(
            "SELECT run_use_count FROM learning_queue WHERE candidate_id=?", (cid,)
        ).fetchone()[0]
    attempt = uuid4().hex
    executions = []
    for index in range(count):
        education = MissionPlanner(
            db_path=work / "learning.db"
        )._plan_neuron_education()
        if not education:
            break
        executions.append(
            execute(
                education[0].task_type,
                {**education[0].payload, "correlation_id": correlation},
                f"certified-application:{attempt}:{index}",
            )
        )
    with sqlite3.connect(work / "learning.db") as conn:
        conn.row_factory = sqlite3.Row
        after = conn.execute(
            "SELECT run_use_count FROM learning_queue WHERE candidate_id=?", (cid,)
        ).fetchone()[0]
        assignments = [
            dict(x)
            for x in conn.execute(
                "SELECT assignment_id,neuron_id,session_id,status,use_count,outcome_score FROM neuron_learning_assignments WHERE candidate_id=?",
                (cid,),
            )
        ]
        applications = [
            dict(x)
            for x in conn.execute(
                "SELECT a.* FROM neuron_education_applications a JOIN neuron_learning_assignments n ON n.session_id=a.session_id WHERE n.candidate_id=? ORDER BY a.created_at",
                (cid,),
            )
        ]
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tested_source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "correlation_id": correlation,
        "candidate_id": cid,
        "distribution": distribution,
        "application": executions[-1] if executions else None,
        "application_executions": executions,
        "run_use_count_before": before,
        "run_use_count_after": after,
        "assignments": assignments,
        "applications": applications,
        "scope": "Normal WorkerLoop, TriadeRunner and productive injector in existing experiment DB; no production state writes or full-chain certification",
        "truth": after - before >= count and len(applications) >= count,
        "full_learning_circuit_closed": False,
    }
    out = ROOT / "reports/evolution/admission_productive_use_latest.json"
    if out.exists():
        out.with_name(f"admission_productive_use_attempt-{attempt}.json").write_bytes(
            out.read_bytes()
        )
    out.write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "truth": result["truth"],
                "uses_before": before,
                "uses_after": after,
                "applications_executed": len(executions),
            }
        )
    )
    return 0 if result["truth"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
