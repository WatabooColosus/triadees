#!/usr/bin/env python3
"""Run the bounded compatibility and rollback window for Phase 2."""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.runtime.legacy_compatibility import LegacyCompatibilityController
from triade.runtime.legacy_task_reconciler import LegacyTaskReconciler
from triade.runtime.task_leases import AutonomousTaskStore
from triade.workers.state_store import WorkerStateStore
from triade.workers.task_queue import WorkerTaskQueue


def run_validation() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="triade-phase-02-") as directory:
        db_path = Path(directory) / "runtime.db"
        legacy = WorkerStateStore(db_path)
        controller = LegacyCompatibilityController(db_path)
        canonical = AutonomousTaskStore(db_path)

        controller.set_compatibility(
            enabled=True, actor="phase-02-runner", reason="bounded migration window"
        )
        legacy_rows = [
            legacy.enqueue_task("pulse_check", {"legacy_index": index})
            for index in range(3)
        ]
        controller.set_compatibility(
            enabled=False, actor="phase-02-runner", reason="migration window closed"
        )

        links: list[tuple[int, str]] = []
        for legacy_task in legacy_rows:
            legacy_id = int(legacy_task.id or 0)
            claimed = legacy.claim_next_task()
            if claimed is None:
                raise RuntimeError("legacy_replay_claim_missing")
            v2 = canonical.enqueue(
                claimed.task_type,
                claimed.payload,
                idempotency_key=f"legacy-worker-task:{legacy_id}",
                priority=claimed.priority,
            )
            linked = legacy.link_delegated_task(legacy_id, str(v2["task_id"]))
            if not linked:
                raise RuntimeError("legacy_replay_link_failed")
            same = canonical.enqueue(
                claimed.task_type,
                claimed.payload,
                idempotency_key=f"legacy-worker-task:{legacy_id}",
                priority=claimed.priority,
            )
            checks[f"idempotent_legacy_{legacy_id}"] = same["task_id"] == v2["task_id"]
            links.append((legacy_id, str(v2["task_id"])))

        for _legacy_id, task_id in links:
            claimed = canonical.claim_task(task_id, "phase-02-reconciler")
            if claimed is None:
                raise RuntimeError("canonical_reconciliation_claim_missing")
            canonical.skip(
                task_id,
                "phase-02-reconciler",
                int(claimed["lease_generation"]),
                "compatibility_window_observation_only",
            )

        first_reconcile = LegacyTaskReconciler(db_path).reconcile()
        second_reconcile = LegacyTaskReconciler(db_path).reconcile()
        metrics = controller.metrics()
        checks["duplicates_zero"] = metrics["duplicate_links"] == 0
        checks["losses_zero"] = metrics["legacy_linked"] == len(legacy_rows)
        checks["reconciliation_idempotent"] = (
            first_reconcile["repaired"] == len(legacy_rows)
            and second_reconcile == {"repaired": 0, "errors": 0}
            and metrics["legacy_pending_reconciliation"] == 0
        )

        blocked = False
        try:
            legacy.enqueue_task("pulse_check", {"must_be_blocked": True})
        except sqlite3.IntegrityError as exc:
            blocked = "legacy_worker_task_writes_disabled" in str(exc)
        checks["legacy_write_blocked"] = blocked

        controller.set_compatibility(
            enabled=True,
            actor="phase-02-runner",
            reason="explicit rollback drill",
        )
        restored = legacy.enqueue_task("pulse_check", {"rollback_probe": True})
        checks["rollback_restores_compatibility"] = restored.id is not None
        controller.set_compatibility(
            enabled=False,
            actor="phase-02-runner",
            reason="rollback drill complete",
        )

        queue = WorkerTaskQueue(db_path)
        high = queue.enqueue("pulse_check", {"order": "high"}, priority=80)
        low = queue.enqueue("pulse_check", {"order": "low"}, priority=10)
        duplicate = queue.enqueue("pulse_check", {"order": "low"}, priority=10)
        claimed = canonical.claim("phase-02-order")
        checks["canonical_active_deduplication"] = duplicate.id == low.id
        checks["stable_priority_order"] = bool(claimed and claimed["task_id"] == low.id)
        details.update(
            {
                "links": links,
                "first_reconcile": first_reconcile,
                "second_reconcile": second_reconcile,
                "metrics": metrics,
                "priority_probe": {
                    "high": high.id,
                    "low": low.id,
                    "claimed": claimed["task_id"] if claimed else None,
                },
                "final_compatibility": controller.status(),
            }
        )

    return {
        "phase": 2,
        "certification": "TRIADE-VERIFY-v1",
        "executed_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "details": details,
        "passed": bool(checks) and all(checks.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/triade_verify/phase_02/legacy_retirement.json",
    )
    args = parser.parse_args()
    report = run_validation()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
