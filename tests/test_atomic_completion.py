from __future__ import annotations

from pathlib import Path

from triade.runtime.atomic_completion import AtomicCompletionCoordinator
from triade.runtime.task_artifacts import CanonicalTaskArtifacts
from triade.runtime.task_leases import AutonomousTaskStore


def _prepared(tmp_path: Path):
    db_path = tmp_path / "tasks.db"
    store = AutonomousTaskStore(db_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="atomic")
    claimed = store.claim("worker")
    assert claimed
    artifacts = CanonicalTaskArtifacts(tmp_path / "run", task["task_id"])
    staging = artifacts.staging_path()
    artifacts.finalize(
        task=task,
        execution={},
        result={"status": "completed"},
        worker_id="worker",
        lease_generation=claimed["lease_generation"],
        payload_hash=task["payload_hash"],
        status="completed",
        target_path=staging,
    )
    return store, task, claimed, artifacts, staging


def test_failure_before_artifact_write(tmp_path: Path) -> None:
    artifacts = CanonicalTaskArtifacts(tmp_path / "run", "task-real")
    staging = artifacts.staging_path()
    assert not (staging / "result.json").exists()
    assert not artifacts.path.exists()


def test_failure_after_artifact_write_before_db(tmp_path: Path, monkeypatch) -> None:
    store, task, claimed, artifacts, staging = _prepared(tmp_path)
    monkeypatch.setattr(store, "prepare_completion", lambda *args, **kwargs: False)
    assert not AtomicCompletionCoordinator(store).complete(
        task_id=task["task_id"],
        worker_id="worker",
        lease_generation=claimed["lease_generation"],
        artifacts=artifacts,
        staging_path=staging,
    )
    assert store.get(task["task_id"])["status"] == "leased"
    assert staging.exists()


def test_failure_after_db_before_final_rename(tmp_path: Path, monkeypatch) -> None:
    store, task, claimed, artifacts, staging = _prepared(tmp_path)
    monkeypatch.setattr(
        artifacts, "publish", lambda _path: (_ for _ in ()).throw(OSError("rename"))
    )
    assert not AtomicCompletionCoordinator(store).complete(
        task_id=task["task_id"],
        worker_id="worker",
        lease_generation=claimed["lease_generation"],
        artifacts=artifacts,
        staging_path=staging,
    )
    assert store.get(task["task_id"])["status"] == "completion_uncertain"


def test_completion_uncertain_is_reconciled(tmp_path: Path) -> None:
    store, task, claimed, artifacts, staging = _prepared(tmp_path)
    assert store.prepare_completion(
        task["task_id"],
        "worker",
        claimed["lease_generation"],
        str(artifacts.path / "result.json"),
    )
    artifacts.publish(staging)
    result = store.reconcile_uncertain_completions()
    assert result == {"completed": 1, "still_uncertain": 0}
    assert store.get(task["task_id"])["status"] == "completed"


def test_event_failure_does_not_create_false_success(tmp_path: Path) -> None:
    store, task, claimed, artifacts, staging = _prepared(tmp_path)

    def fail_event() -> None:
        raise RuntimeError("event unavailable")

    assert not AtomicCompletionCoordinator(store).complete(
        task_id=task["task_id"],
        worker_id="worker",
        lease_generation=claimed["lease_generation"],
        artifacts=artifacts,
        staging_path=staging,
        event_recorder=fail_event,
    )
    assert store.get(task["task_id"])["status"] == "completion_uncertain"


def test_db_failure_does_not_create_false_success(tmp_path: Path, monkeypatch) -> None:
    store, task, claimed, artifacts, staging = _prepared(tmp_path)
    monkeypatch.setattr(store, "finalize_completion", lambda *args, **kwargs: False)
    assert not AtomicCompletionCoordinator(store).complete(
        task_id=task["task_id"],
        worker_id="worker",
        lease_generation=claimed["lease_generation"],
        artifacts=artifacts,
        staging_path=staging,
    )
    assert store.get(task["task_id"])["status"] == "completion_uncertain"
    assert artifacts.path.exists()
