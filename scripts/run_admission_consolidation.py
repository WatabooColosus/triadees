"""Verify consolidation through the existing planner and governed worker."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_store import SemanticMemoryStore
from triade.workers.contracts import WorkerRunConfig
from triade.workers.mission_planner import MissionPlanner
from triade.workers.worker_loop import WorkerLoop

ROOT = Path(__file__).resolve().parents[1]
TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-existing", action="store_true")
    verify_existing = parser.parse_args().verify_existing
    previous = json.loads(
        (ROOT / "reports/evolution/productive_learning_chain_v3.json").read_text(
            encoding="utf-8"
        )
    )
    application = json.loads(
        (ROOT / "reports/evolution/admission_productive_use_latest.json").read_text(
            encoding="utf-8"
        )
    )
    if not application.get("truth") or not any(
        a["use_count"] >= 5 and a["status"] == "beneficial"
        for a in application["assignments"]
    ):
        raise RuntimeError("measured_productive_education_required")
    work = Path(previous["artifact_ref"]).resolve()
    if not work.is_relative_to(ROOT / "artifacts/evolution"):
        raise ValueError("experiment_outside_authorized_scope")
    cid, correlation = previous["candidate_id"], previous["correlation_id"]
    pipeline = LearningPipeline(work / "learning.db")
    before = pipeline.get_candidate(cid)
    path = ROOT / "reports/evolution/admission_consolidation_latest.json"
    if verify_existing:
        recorded = json.loads(path.read_text(encoding="utf-8"))
        after = pipeline.get_candidate(cid)
        document_id = (
            (after.get("verification_notes") or {})
            .get("consolidated", {})
            .get("semantic_document_id")
        )
        document = (
            SemanticMemoryStore(work / "learning.db").get_document(document_id)
            if document_id
            else None
        )
        task = WorkerLoop(db_path=work / "learning.db").autonomous_tasks.get(
            recorded["task"]["task_id"]
        )
        result = {
            **recorded,
            "verification_timestamp": datetime.now(UTC).isoformat(),
            "verification_source_sha": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "after": after,
            "stable_document": document,
            "stable_knowledge_id": document_id,
            "correction": "semantic ID is retained in the consolidation receipt/verification_notes, not as a learning_queue column",
            "truth": bool(
                task
                and task["status"] == "completed"
                and recorded["before"]["status"] != "consolidated"
                and after["status"] == "consolidated"
                and document
                and document["status"] == "stable"
                and document["content"] == after["content"]
            ),
        }
        path.with_name(
            f"admission_consolidation_attempt-{uuid4().hex}.json"
        ).write_bytes(path.read_bytes())
        path.write_text(
            json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "truth": result["truth"],
                    "stable_knowledge_id": document_id,
                    "scope": "receipt and stable document verification; no new consolidation executed",
                }
            )
        )
        return 0 if result["truth"] else 1
    planned = MissionPlanner(db_path=work / "learning.db")._plan_memory_consolidation()
    if not planned:
        raise RuntimeError("no_planned_consolidation")
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    loop = WorkerLoop(
        db_path=work / "learning.db",
        runs_dir=work / "runs",
        lock_file=work / "consolidation.lock",
        stop_file=work / "consolidation.stop",
    )
    task = loop.autonomous_tasks.enqueue(
        planned[0].task_type,
        {**planned[0].payload, "correlation_id": correlation},
        idempotency_key=f"admission-consolidation:{cid}:{sha}",
        max_attempts=1,
    )
    lease = loop.autonomous_tasks.claim_task(
        task["task_id"], correlation, lease_seconds=240
    )
    if lease is None:
        raise RuntimeError("consolidation_task_not_claimable")
    outcome = loop._execute_autonomous_task(
        lease,
        correlation,
        work / "runs",
        WorkerRunConfig(task_timeout=180, concurrency_enabled=False),
        {"tasks_completed": 0, "tasks_blocked": 0, "errors": []},
    )
    after = pipeline.get_candidate(cid)
    document_id = (
        (after.get("verification_notes") or {})
        .get("consolidated", {})
        .get("semantic_document_id")
    )
    document = (
        SemanticMemoryStore(work / "learning.db").get_document(document_id)
        if document_id
        else None
    )
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tested_source_sha": sha,
        "candidate_id": cid,
        "correlation_id": correlation,
        "before": before,
        "after": after,
        "task": loop.autonomous_tasks.get(task["task_id"]),
        "outcome": outcome,
        "scope": "Normal low-risk automatic consolidation in existing experiment DB; no named-human override",
        "stable_knowledge_id": document_id,
        "stable_document": document,
        "truth": before["status"] != "consolidated"
        and after["status"] == "consolidated"
        and bool(
            document
            and document["status"] == "stable"
            and document["content"] == after["content"]
        ),
    }
    if path.exists():
        path.with_name(
            f"admission_consolidation_attempt-{uuid4().hex}.json"
        ).write_bytes(path.read_bytes())
    path.write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "truth": result["truth"],
                "before": before["status"],
                "after": after["status"],
                "rejected": outcome.get("rejected"),
                "document_id": document_id,
            }
        )
    )
    return 0 if result["truth"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
