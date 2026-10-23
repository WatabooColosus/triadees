"""Execute a planned admission curriculum through the normal leased WorkerLoop.

Reuses the existing experimental DB and candidate. No production row seeding,
manual activation, or mock model output is used by this verification command.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from triade.workers.contracts import WorkerRunConfig
from triade.workers.mission_planner import MissionPlanner
from triade.workers.worker_loop import WorkerLoop

ROOT = Path(__file__).resolve().parents[1]
TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase", choices=("training", "certification"), default="training"
    )
    phase = parser.parse_args().phase
    prior = json.loads(
        (ROOT / "reports/evolution/productive_learning_chain_v3.json").read_text(
            encoding="utf-8"
        )
    )
    work = Path(prior["artifact_ref"]).resolve()
    if not work.is_relative_to(ROOT / "artifacts/evolution"):
        raise ValueError("experiment_outside_authorized_scope")
    planned = MissionPlanner(db_path=work / "learning.db")._plan_neuron_formation()
    target = next(
        (item for item in planned if item.payload.get("admission_phase") == phase), None
    )
    if target is None:
        raise RuntimeError("no_planned_admission_training")
    correlation_id = target.payload["correlation_id"]
    loop = WorkerLoop(
        db_path=work / "learning.db",
        runs_dir=work / "runs",
        lock_file=work / "training.lock",
        stop_file=work / "training.stop",
    )
    task = loop.autonomous_tasks.enqueue(
        target.task_type,
        target.payload,
        idempotency_key=f"admission-{phase}:{target.payload['admission_event_id']}",
        max_attempts=1,
    )
    lease = loop.autonomous_tasks.claim_task(
        task["task_id"], correlation_id, lease_seconds=180
    )
    if lease is None:
        raise RuntimeError("training_task_not_claimable")
    outcome = loop._execute_autonomous_task(
        lease,
        correlation_id,
        work / "runs",
        WorkerRunConfig(task_timeout=120, concurrency_enabled=False),
        {"tasks_completed": 0, "tasks_blocked": 0, "errors": []},
    )
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tested_source_sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain", "--", "triade", "scripts", "tests"],
                cwd=ROOT,
                text=True,
            ).strip()
        ),
        "correlation_id": correlation_id,
        "task": loop.autonomous_tasks.get(task["task_id"]),
        "outcome": outcome,
        "scope": "Normal WorkerLoop and Ollama in existing experiment DB; not productive education certification",
        "truth": outcome.get("training", {}).get("status")
        == ("certified" if phase == "certification" else "training_completed"),
    }
    path = ROOT / f"reports/evolution/admission_{phase}_latest.json"
    if path.exists():
        path.with_name(f"admission_training_attempt-{uuid4().hex}.json").write_bytes(
            path.read_bytes()
        )
    path.write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "task_status": result["task"]["status"],
                "training": outcome.get("training"),
                "truth": result["truth"],
            }
        )
    )
    return 0 if result["truth"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
