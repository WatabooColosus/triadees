from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from triade.core.central import PlanGraph, PlanStep
from triade.learning.validation import LearningValidationReceipt
from triade.runtime.effect_receipt import EffectReceipt
from triade.runtime.evidence_provenance import EvidenceProvenanceStore
from triade.runtime.execution_result import ExecutionResult
from triade.runtime.governed_plan_dispatcher import GovernedPlanDispatcher
from triade.runtime.governed_task_executor import GovernedTaskExecutor
from triade.runtime.resource_ledger import ResourceMeasurement
from triade.runtime.task_leases import AutonomousTaskStore


def _late_effect(path: str) -> dict:
    time.sleep(1)
    Path(path).write_text("should-not-exist", encoding="utf-8")
    return {"status": "completed"}


def _running(store: AutonomousTaskStore, key: str) -> tuple[dict, int]:
    task = store.enqueue("pulse_check", {}, idempotency_key=key)
    claimed = store.claim("worker")
    assert claimed
    return task, int(claimed["lease_generation"])


def test_no_completed_without_execution_evidence() -> None:
    with pytest.raises(ValidationError):
        ExecutionResult(status="completed", executed=True)


@pytest.mark.parametrize("terminal", ["blocked", "skipped", "dry_run"])
def test_no_completed_from_non_execution(tmp_path: Path, terminal: str) -> None:
    store = AutonomousTaskStore(tmp_path / f"{terminal}.db")
    task, generation = _running(store, terminal)
    transition = {
        "blocked": store.block,
        "skipped": store.skip,
        "dry_run": store.mark_dry_run,
    }[terminal]
    assert transition(task["task_id"], "worker", generation, "truth")
    result = tmp_path / f"{terminal}.json"
    result.write_text("{}", encoding="utf-8")
    assert not store.complete(task["task_id"], "worker", generation, str(result))


def test_no_duplicate_effect_per_idempotency_key(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "idempotency.db")
    one = store.enqueue("work", {"x": 1}, idempotency_key="effect:1")
    two = store.enqueue("work", {"x": 1}, idempotency_key="effect:1")
    assert one["task_id"] == two["task_id"]


def test_no_stale_lease_completion(tmp_path: Path) -> None:
    db = tmp_path / "lease.db"
    store = AutonomousTaskStore(db)
    task, old_generation = _running(store, "lease")
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), task["task_id"]),
        )
    store.recover_expired()
    store.claim("other")
    result = tmp_path / "stale.json"
    result.write_text("{}", encoding="utf-8")
    assert not store.complete(task["task_id"], "worker", old_generation, str(result))


def test_no_learning_without_evaluation() -> None:
    with pytest.raises(ValidationError):
        LearningValidationReceipt(
            learning_id="x", status="validated", hypothesis="h", producer_id="p",
            created_at="now", updated_at="now",
        )


def test_no_rollback_claim_without_rollback_test() -> None:
    with pytest.raises(ValidationError):
        EffectReceipt(
            action="rollback", target="x", postcondition={"passed": True},
            verified=True, verifier="claim",
        )


def test_no_artifact_reference_to_missing_file(tmp_path: Path) -> None:
    store = AutonomousTaskStore(tmp_path / "artifact.db")
    task, generation = _running(store, "artifact")
    assert not store.complete(
        task["task_id"], "worker", generation, str(tmp_path / "missing")
    )


def test_no_external_effect_without_policy_decision(tmp_path: Path) -> None:
    graph = PlanGraph(plan_id="policy", goal="test", steps=[])
    step = PlanStep(id="write", description="crea un archivo")
    graph.steps.append(step)
    receipt = GovernedPlanDispatcher(tmp_path / "policy.db").dispatch(graph, step)
    assert receipt.status == "blocked"
    assert receipt.task_id is None


def test_no_resource_value_without_measurement_type() -> None:
    with pytest.raises(ValueError):
        ResourceMeasurement("cpu", 1, "seconds", "invented", "x", "a", "b")


def test_no_plan_completion_without_terminal_verified_steps() -> None:
    graph = PlanGraph(steps=[PlanStep(id="x", state="queued")])
    graph.close()
    assert graph.status == "partial"


def test_no_autonomous_evidence_presented_as_external(tmp_path: Path) -> None:
    evidence = EvidenceProvenanceStore(tmp_path / "evidence.db").create(
        origin_class="autonomous", producer_id="worker", source="cycle", content="x"
    )
    assert not evidence.independently_external


def test_no_timeout_that_leaves_process_running(tmp_path: Path) -> None:
    delayed = tmp_path / "late.txt"
    outcome = GovernedTaskExecutor(tmp_path / "quarantine").execute_callable(
        _late_effect, args=(str(delayed),), timeout_seconds=0.1,
        artifact_dir=tmp_path / "task",
    )
    assert outcome.status == "timeout"
    time.sleep(0.2)
    assert not delayed.exists()


def test_file_hash_evidence_is_real(tmp_path: Path) -> None:
    target = tmp_path / "real.txt"
    target.write_text("real", encoding="utf-8")
    receipt = EffectReceipt.verify_file(target, hashlib.sha256(b"real").hexdigest())
    assert receipt.verified
