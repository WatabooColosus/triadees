"""Exercise the normal leased WorkerLoop handler in the real experiment sandbox.

No production state writes, no fabricated neuron or education rows. This is an
integration experiment, not a claim that the complete cognitive chain passes.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from scripts.run_level8_learning_transfer import ROOT
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop

TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main():
    os.environ["TRIADE_LOW_RESOURCE_MODE"] = "1"
    previous = json.loads(
        (ROOT / "reports/evolution/learning_transfer_latest.json").read_text(
            encoding="utf-8"
        )
    )
    if not previous.get("truth"):
        raise RuntimeError("causal_transfer_prerequisite_not_met")
    work = Path(previous["artifact_ref"])
    cid = previous["knowledge_created"]["candidate_id"]
    loop = WorkerLoop(
        db_path=work / "learning.db",
        runs_dir=work / "runs",
        lock_file=work / "worker.lock",
        stop_file=work / "stop",
    )
    out = ROOT / "reports/evolution/productive_learning_chain_latest.json"
    if out.exists():
        (
            out.parent / f"productive_learning_attempt-{uuid.uuid4().hex}.json"
        ).write_bytes(out.read_bytes())
    correlation_id = "evolution-" + uuid.uuid4().hex
    task = loop.autonomous_tasks.enqueue(
        "learning_evidence_generation",
        {"candidate_id": cid, "repetitions": 5, "correlation_id": correlation_id},
        idempotency_key="evolution-evidence-" + correlation_id,
        max_attempts=1,
    )
    leased = loop.autonomous_tasks.claim_task(
        task["task_id"], correlation_id, lease_seconds=300
    )
    if leased is None:
        raise RuntimeError("experiment_task_not_claimable")
    config = WorkerRunConfig(task_timeout=120, concurrency_enabled=False)
    summary = {"tasks_completed": 0, "tasks_blocked": 0, "errors": []}
    outcome = loop._execute_autonomous_task(
        leased, correlation_id, work / "runs", config, summary
    )
    route = None
    try:
        from triade.neurons.learning_router import NeuralLearningRouter

        route = NeuralLearningRouter(work / "learning.db").route(cid)
    except (ValueError, KeyError, RuntimeError) as exc:
        route = {"status": "BLOCKED", "reason": str(exc)}
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "correlation_id": correlation_id,
        "candidate_id": cid,
        "task_id": task["task_id"],
        "task": loop.autonomous_tasks.get(task["task_id"]),
        "worker_outcome": outcome,
        "route": route,
        "summary": summary,
        "artifact_ref": str(work),
        "scope": "Normal leased WorkerLoop + subprocess handler in isolated experiment; complete education/use chain NOT certified",
        "truth": False,
        "production_writes": False,
    }
    (ROOT / "reports/evolution/productive_learning_chain_latest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "task_status": result["task"]["status"],
                "worker_outcome": outcome.get("decision"),
                "route": route,
            }
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
