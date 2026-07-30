#!/usr/bin/env python3
"""Reproduce the Phase 1 execution-truth invariants with real local effects."""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from triade.os.autonomous_routines import AutonomousRoutines
from triade.runtime.effect_receipt import EffectReceipt
from triade.runtime.execution_result import ExecutionResult
from triade.runtime.governed_capability import GovernedFileWriteCapability
from triade.runtime.governed_task_executor import GovernedTaskExecutor
from triade.runtime.task_leases import AutonomousTaskStore


def _late_write(path: str) -> dict[str, Any]:
    time.sleep(1)
    Path(path).write_text("late-effect", encoding="utf-8")
    return {"status": "completed"}


def _rejected(function: Any, expected: str) -> bool:
    try:
        function()
    except (ValidationError, ValueError) as exc:
        return expected in str(exc)
    return False


def run_validation() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="triade-phase-01-") as directory:
        root = Path(directory)

        routines = AutonomousRoutines(str(root / "legacy.db"))
        blocked = routines.create_routine("autonomous_research")
        observed = routines.create_routine("health_maintenance")
        blocked_result = routines.execute_routine(blocked["routine_id"])
        observed_result = routines.execute_routine(observed["routine_id"])
        checks["blocked_never_completed"] = blocked_result["status"] == "blocked"
        checks["observed_never_completed"] = observed_result["status"] == "observed"
        checks["legacy_improvement_write_blocked"] = (
            routines.record_improvement("x", "x", "x")["status"] == "blocked"
            and routines.improvements() == []
        )
        details["legacy"] = {
            "blocked": blocked_result["status"],
            "observed": observed_result["status"],
        }

        checks["completed_requires_receipt"] = _rejected(
            lambda: ExecutionResult(
                status="completed", executed=True, evidence=["claim"]
            ),
            "completed_requires_verified_effect_receipt",
        )
        observation_receipt = EffectReceipt(
            action="observe",
            target="runtime",
            postcondition={"passed": True},
            verified=True,
            verifier="phase_01_probe",
            evidence_refs=["probe"],
        )
        checks["completed_requires_artifact_when_declared"] = _rejected(
            lambda: ExecutionResult(
                status="completed",
                executed=True,
                evidence=["probe"],
                postconditions={"artifact_required": True},
                effect_receipt=observation_receipt,
            ),
            "completed_requires_artifact",
        )
        checks["reversible_requires_rollback_ref"] = _rejected(
            lambda: EffectReceipt(
                action="write_file",
                target="target",
                postcondition={"passed": True},
                verified=True,
                verifier="phase_01_probe",
                evidence_refs=["probe"],
                rollback_required=True,
            ),
            "reversible_effect_requires_rollback_ref",
        )

        late_path = root / "late.txt"
        timeout = GovernedTaskExecutor(root / "quarantine").execute_callable(
            _late_write,
            args=(str(late_path),),
            timeout_seconds=0.1,
            artifact_dir=root / "timeout-artifact",
        )
        time.sleep(0.2)
        checks["timeout_rejects_late_effect"] = (
            timeout.status == "timeout" and not late_path.exists()
        )
        details["timeout"] = timeout.to_dict()

        task_db = root / "tasks.db"
        store = AutonomousTaskStore(task_db)
        task = store.enqueue("work", {}, idempotency_key="phase-01-fencing")
        old = store.claim("old-worker", lease_seconds=1)
        if old is None:
            raise RuntimeError("phase_01_probe_could_not_claim_task")
        with sqlite3.connect(task_db) as conn:
            conn.execute(
                "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
                (
                    (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                    task["task_id"],
                ),
            )
        store.recover_expired()
        new = store.claim("new-worker")
        stale_ref = root / "stale-result.json"
        stale_ref.write_text("{}", encoding="utf-8")
        stale_accepted = store.complete(
            task["task_id"],
            "old-worker",
            int(old["lease_generation"]),
            str(stale_ref),
        )
        checks["stale_fencing_cannot_publish"] = bool(
            new
            and int(new["lease_generation"]) > int(old["lease_generation"])
            and not stale_accepted
        )
        details["fencing"] = {
            "old_generation": old["lease_generation"],
            "new_generation": new["lease_generation"] if new else None,
            "stale_accepted": stale_accepted,
        }

        target = root / "authorized" / "effect.txt"
        target.parent.mkdir()
        capability = GovernedFileWriteCapability(
            target,
            "verified-effect",
            root / "rollback",
            authorized_root=target.parent,
        )
        capability.prepare()
        capability.execute()
        receipt = capability.verify()
        capability.rollback()
        rollback = capability.verify_rollback()
        checks["reversible_effect_has_receipt_and_rollback"] = (
            receipt.verified
            and receipt.rollback_required
            and bool(receipt.rollback_ref)
            and rollback.verified
            and not target.exists()
        )
        details["governed_file"] = {
            "effect_verified": receipt.verified,
            "rollback_ref_present": bool(receipt.rollback_ref),
            "rollback_verified": rollback.verified,
            "target_absent_after_rollback": not target.exists(),
        }

    return {
        "phase": 1,
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
        default="artifacts/triade_verify/phase_01/execution_truth.json",
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
