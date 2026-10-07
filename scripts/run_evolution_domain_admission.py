"""Observe governed admission through the normal leased WorkerLoop handler.

Reuses the actual prior experiment DB. Does not seed neurons or manufacture
training outcomes. An unresolved certificate remains an explicit failed gate.
"""
from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop

ROOT = Path(__file__).resolve().parents[1]
TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main() -> int:
    previous = json.loads((ROOT / "reports/evolution/learning_transfer_latest.json").read_text(encoding="utf-8"))
    work = Path(previous["artifact_ref"]).resolve()
    if not work.is_relative_to(ROOT / "artifacts/evolution"):
        raise ValueError("experiment_directory_outside_authorized_scope")
    candidate_id = previous["knowledge_created"]["candidate_id"]
    correlation_id = "admission-" + uuid4().hex
    loop = WorkerLoop(db_path=work / "learning.db", runs_dir=work / "runs",
                      lock_file=work / "admission.lock", stop_file=work / "admission.stop")
    task = loop.autonomous_tasks.enqueue(
        "neural_learning_distribution",
        {"candidate_id": candidate_id, "correlation_id": correlation_id},
        idempotency_key=correlation_id, max_attempts=1,
    )
    leased = loop.autonomous_tasks.claim_task(task["task_id"], correlation_id, lease_seconds=120)
    if leased is None:
        raise RuntimeError("admission_task_not_claimable")
    summary = {"tasks_completed": 0, "tasks_blocked": 0, "errors": []}
    outcome = loop._execute_autonomous_task(
        leased, correlation_id, work / "runs",
        WorkerRunConfig(task_timeout=60, concurrency_enabled=False), summary,
    )
    admission = outcome.get("domain_admission")
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "correlation_id": correlation_id, "candidate_id": candidate_id,
        "domain": admission.get("domain") if admission else None,
        "formation": admission, "education": {"status": "NOT_DEMONSTRATED"},
        "certification": {"status": "NOT_DEMONSTRATED"},
        "activation": {"activated": False},
        "task": loop.autonomous_tasks.get(task["task_id"]),
        "worker_outcome": outcome,
        "knowledge_retrieved": False, "knowledge_used": False,
        "control_score": None, "treatment_score": None,
        "verification_report": None, "consolidated": False,
        "truth": False, "production_writes": False,
        "scope": "Normal leased admission handler in existing experiment DB; no neuron activation or productive education claim",
        "artifact_ref": str(work),
    }
    out = ROOT / "reports/evolution/productive_learning_chain_v2.json"
    if out.exists():
        (out.parent / f"domain_admission_attempt-{uuid4().hex}.json").write_bytes(out.read_bytes())
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"task_status": report["task"]["status"],
                      "admission_status": admission.get("status") if admission else None,
                      "truth": False}))
    return 0 if admission and report["task"]["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
