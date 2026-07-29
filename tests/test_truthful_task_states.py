from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from triade.runtime.execution_result import ExecutionResult
from triade.runtime.task_leases import AutonomousTaskStore
from triade.workers.worker_loop import WorkerLoop


def _running(store: AutonomousTaskStore, key: str) -> dict:
    task = store.enqueue("pulse_check", {}, idempotency_key=key)
    claimed = store.claim("worker")
    assert claimed and claimed["task_id"] == task["task_id"]
    generation = int(claimed["lease_generation"])
    assert store.start(task["task_id"], "worker", generation)
    return {**task, "lease_generation": generation}


def test_blocked_task_never_completes(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = _running(store, "blocked")
    assert store.block(
        task["task_id"], "worker", task["lease_generation"], "policy_denied"
    )
    assert store.get(task["task_id"])["status"] == "blocked"
    assert not store.complete(
        task["task_id"], "worker", task["lease_generation"], "result.json"
    )


def test_skipped_task_never_completes(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = _running(store, "skipped")
    assert store.skip(task["task_id"], "worker", task["lease_generation"], "not_due")
    assert store.get(task["task_id"])["status"] == "skipped"


def test_dry_run_never_completes(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = _running(store, "dry-run")
    assert store.mark_dry_run(
        task["task_id"], "worker", task["lease_generation"], "dry_run_requested"
    )
    assert store.get(task["task_id"])["status"] == "dry_run"


def test_observed_task_never_claims_execution() -> None:
    result = ExecutionResult(status="observed", executed=False, message="inspected")
    assert result.executed is False
    with pytest.raises(ValidationError, match="observed_requires_executed_false"):
        ExecutionResult(status="observed", executed=True)


def test_only_completed_path_marks_completed(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = _running(store, "completed")
    result_ref = tmp_path / "result.json"
    result_ref.write_text("{}", encoding="utf-8")
    assert store.complete(
        task["task_id"], "worker", task["lease_generation"], str(result_ref)
    )
    assert store.get(task["task_id"])["status"] == "completed"


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ExecutionResult.model_validate({"status": "pretend_success", "executed": True})
    with pytest.raises(ValueError, match="unknown_handler_status"):
        WorkerLoop._canonical_execution_result({"status": "pretend_success"}, "missing")


def test_execution_result_invariants() -> None:
    with pytest.raises(ValidationError, match="completed_requires_executed_true"):
        ExecutionResult(status="completed", executed=False, evidence=["run:1"])
    with pytest.raises(ValidationError, match="completed_requires_evidence"):
        ExecutionResult(status="completed", executed=True)
    with pytest.raises(ValidationError, match="completed_effect_requires"):
        ExecutionResult(
            status="completed",
            executed=True,
            evidence=["run:1"],
            postconditions={"effect_expected": True},
        )
    with pytest.raises(ValidationError, match="failed_result_cannot_claim"):
        ExecutionResult(status="failed", executed=True, postconditions={"passed": True})
    with pytest.raises(ValidationError, match="dry_run_cannot_apply_effect"):
        ExecutionResult(status="dry_run", executed=False, effect_applied=True)
