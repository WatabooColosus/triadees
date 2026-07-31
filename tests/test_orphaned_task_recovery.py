from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from triade.runtime.task_leases import AutonomousTaskStore

# ── helpers ──────────────────────────────────────────────────────────


def _expire_lease(db: Path, task_id: str) -> None:
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET lease_expires_at=? WHERE task_id=?",
            (past, task_id),
        )


def _make_lock(db: Path, pid: int) -> Path:
    lock = db.parent / "worker.lock"
    from triade.runtime.process_lock import RuntimeProcessLock

    lock.write_bytes(RuntimeProcessLock.payload(pid=pid))
    return lock


def _alive_pid() -> int:
    return os.getpid()


def _dead_pid() -> int:
    for candidate in (999999, 999998, 999997, 1):
        try:
            os.kill(candidate, 0)
        except (ProcessLookupError, PermissionError, OSError):
            return candidate
    return 2


# ── Test: leased ─────────────────────────────────────────────────────


def test_leased_orphan_is_recovered(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="leased-orphan")
    claimed = store.claim("dead-worker", lease_seconds=30)
    assert claimed and claimed["status"] == "leased"
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    result = store.recover_orphaned_tasks()
    assert result["leased_recovered"] == 1
    assert result["fencing_invalidated"] == 1
    recovered = store.get(task["task_id"])
    assert recovered["status"] == "recovered"
    assert recovered["worker_id"] is None
    assert recovered["lease_acquired_at"] is None
    assert recovered["lease_expires_at"] is None


def test_leased_orphan_becomes_claimable(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="leased-claimable")
    old = store.claim("dead-worker", lease_seconds=30)
    assert old
    old_gen = old["lease_generation"]
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    store.recover_orphaned_tasks()
    reclaimed = store.claim("new-worker")
    assert reclaimed is not None
    assert reclaimed["lease_generation"] > old_gen
    assert reclaimed["status"] == "leased"


def test_leased_with_live_lock_is_not_touched(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="leased-protected")
    claimed = store.claim("live-worker", lease_seconds=30)
    assert claimed
    lock = _make_lock(tmp_path / "tasks.db", _alive_pid())
    result = store.recover_orphaned_tasks(lock_file=lock)
    assert result["status"] == "live_owner"
    assert store.get(task["task_id"])["status"] == "leased"


def test_leased_active_lease_returns_live_lease(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    store.enqueue("work", {}, idempotency_key="leased-fresh")
    now = datetime.now(UTC)
    future = (now + timedelta(hours=1)).isoformat()
    with sqlite3.connect(tmp_path / "tasks.db") as conn:
        conn.execute("UPDATE autonomous_tasks SET lease_expires_at=?", (future,))
    claimed = store.claim("worker-a", lease_seconds=30)
    assert claimed
    result = store.recover_orphaned_tasks(now=now)
    assert result["leased_recovered"] == 0


# ── Test: running ────────────────────────────────────────────────────


def test_running_readonly_orphan_is_recovered(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("pulse_check", {}, idempotency_key="running-ro")
    claimed = store.claim("dead-worker", lease_seconds=30)
    assert claimed
    store.start(task["task_id"], "dead-worker", claimed["lease_generation"])
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    result = store.recover_orphaned_tasks()
    assert result["running_uncertain"] >= 1


def test_running_with_artifact_completes(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("pulse_check", {}, idempotency_key="running-artifact")
    claimed = store.claim("dead-worker", lease_seconds=30)
    assert claimed
    store.start(task["task_id"], "dead-worker", claimed["lease_generation"])
    ref = tmp_path / "result.json"
    ref.write_text('{"status":"completed"}', encoding="utf-8")
    with sqlite3.connect(tmp_path / "tasks.db") as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET result_ref=? WHERE task_id=?",
            (str(ref), task["task_id"]),
        )
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    result = store.recover_orphaned_tasks()
    assert result["running_recovered"] == 1
    assert store.get(task["task_id"])["status"] == "completed"


def test_running_without_artifact_goes_uncertain(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue(
        "experimental_neuron_activity", {}, idempotency_key="running-no-artifact"
    )
    claimed = store.claim("dead-worker", lease_seconds=30)
    assert claimed
    store.start(task["task_id"], "dead-worker", claimed["lease_generation"])
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    result = store.recover_orphaned_tasks()
    assert result["running_uncertain"] >= 1
    assert store.get(task["task_id"])["status"] == "completion_uncertain"
    assert "recovery:no_artifact_found" in (
        store.get(task["task_id"]).get("last_error") or ""
    )


# ── Test: retry_wait ─────────────────────────────────────────────────


def test_retry_wait_preserves_status_and_attempt(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="retry-preserve", max_attempts=3)
    claimed = store.claim("worker-a", lease_seconds=30)
    assert claimed
    retry = store.fail(
        task["task_id"],
        "worker-a",
        claimed["lease_generation"],
        "transient",
        base_delay_seconds=60,
    )
    assert retry["status"] == "retry_wait"
    orig_attempt = retry["attempt"]
    last_err = retry["last_error"]
    result = store.recover_orphaned_tasks()
    assert result["retry_wait_preserved"] >= 1
    recovered = store.get(task["task_id"])
    assert recovered["status"] == "retry_wait"
    assert recovered["attempt"] == orig_attempt
    assert recovered["last_error"] == last_err


def test_retry_wait_retry_after_preserved(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="retry-after", max_attempts=3)
    claimed = store.claim("w", lease_seconds=30)
    assert claimed
    retry = store.fail(
        task["task_id"], "w", claimed["lease_generation"], "err", base_delay_seconds=120
    )
    orig_after = retry["retry_after"]
    store.recover_orphaned_tasks()
    recovered = store.get(task["task_id"])
    assert recovered["retry_after"] == orig_after


def test_retry_wait_with_stale_owner_cleans_worker_id(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue(
        "work", {}, idempotency_key="retry-stale-owner", max_attempts=3
    )
    claimed = store.claim("stale-worker", lease_seconds=1)
    assert claimed
    store.fail(
        task["task_id"],
        "stale-worker",
        claimed["lease_generation"],
        "err",
        base_delay_seconds=60,
    )
    result = store.recover_orphaned_tasks()
    assert result["retry_wait_preserved"] >= 1
    recovered = store.get(task["task_id"])
    assert recovered["worker_id"] is None


# ── Test: deferred ───────────────────────────────────────────────────


def test_deferred_preserves_status(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("research", {}, idempotency_key="deferred-preserve")
    claimed = store.claim("worker-a", lease_seconds=30)
    assert claimed
    store.defer(
        task["task_id"],
        "worker-a",
        claimed["lease_generation"],
        "backpressure",
        delay_seconds=60,
    )
    result = store.recover_orphaned_tasks()
    assert result["deferred_preserved"] >= 1
    recovered = store.get(task["task_id"])
    assert recovered["status"] == "deferred"


def test_deferred_retry_after_preserved(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("research", {}, idempotency_key="deferred-after")
    claimed = store.claim("w", lease_seconds=30)
    assert claimed
    store.defer(
        task["task_id"], "w", claimed["lease_generation"], "bp", delay_seconds=300
    )
    orig_after = store.get(task["task_id"])["retry_after"]
    store.recover_orphaned_tasks()
    assert store.get(task["task_id"])["retry_after"] == orig_after


def test_deferred_with_stale_owner_cleans_worker_id(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("research", {}, idempotency_key="deferred-stale")
    claimed = store.claim("stale-worker", lease_seconds=1)
    assert claimed
    store.defer(
        task["task_id"],
        "stale-worker",
        claimed["lease_generation"],
        "bp",
        delay_seconds=60,
    )
    result = store.recover_orphaned_tasks()
    assert result["deferred_preserved"] >= 1
    recovered = store.get(task["task_id"])
    assert recovered["worker_id"] is None


# ── Test: completion_uncertain ───────────────────────────────────────


def test_uncertain_with_valid_artifact_completes(tmp_path: Path):
    from triade.runtime.task_artifacts import CanonicalTaskArtifacts

    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("pulse_check", {}, idempotency_key="uncertain-artifact")
    claimed = store.claim("worker", lease_seconds=30)
    assert claimed
    store.start(task["task_id"], "worker", claimed["lease_generation"])
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
    assert store.prepare_completion(
        task["task_id"],
        "worker",
        claimed["lease_generation"],
        str(artifacts.path / "result.json"),
    )
    artifacts.publish(staging)
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    result = store.recover_orphaned_tasks()
    assert result["uncertain_completed"] >= 1
    assert store.get(task["task_id"])["status"] == "completed"


def test_uncertain_without_artifact_remains_uncertain(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="uncertain-no-artifact")
    claimed = store.claim("w", lease_seconds=30)
    assert claimed
    store.start(task["task_id"], "w", claimed["lease_generation"])
    store.prepare_completion(
        task["task_id"], "w", claimed["lease_generation"], "/nonexistent/result.json"
    )
    store.recover_orphaned_tasks()
    assert store.get(task["task_id"])["status"] == "completion_uncertain"


# ── Test: attempt ────────────────────────────────────────────────────


def test_attempt_never_reset(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="attempt-preserve")
    claimed = store.claim("dead-worker", lease_seconds=1)
    assert claimed and claimed["attempt"] == 1
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    store.recover_orphaned_tasks()
    recovered = store.get(task["task_id"])
    assert recovered["attempt"] == 1


# ── Test: last_error ─────────────────────────────────────────────────


def test_last_error_preserved(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="error-preserve", max_attempts=3)
    claimed = store.claim("dead-worker", lease_seconds=1)
    assert claimed
    store.fail(
        task["task_id"],
        "dead-worker",
        claimed["lease_generation"],
        "original_error",
        base_delay_seconds=60,
    )
    orig_error = store.get(task["task_id"])["last_error"]
    store.recover_orphaned_tasks()
    assert store.get(task["task_id"])["last_error"] == orig_error


# ── Test: max_attempts exhausted ─────────────────────────────────────


def test_dead_letter_not_resurrected(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="dead-letter", max_attempts=1)
    claimed = store.claim("w", lease_seconds=30)
    assert claimed
    store.fail(
        task["task_id"], "w", claimed["lease_generation"], "final", base_delay_seconds=0
    )
    assert store.get(task["task_id"])["status"] == "dead_letter"
    store.recover_orphaned_tasks()
    assert store.get(task["task_id"])["status"] == "dead_letter"


# ── Test: fencing ────────────────────────────────────────────────────


def test_old_worker_cannot_complete_after_recovery(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="fencing-old")
    old = store.claim("old-worker", lease_seconds=1)
    assert old
    old_gen = old["lease_generation"]
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    store.recover_orphaned_tasks()
    ref = tmp_path / "late.json"
    ref.write_text("{}", encoding="utf-8")
    assert not store.complete(task["task_id"], "old-worker", old_gen, str(ref))
    new = store.claim("new-worker")
    assert new


def test_no_double_effect(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="no-double")
    claimed = store.claim("w", lease_seconds=1)
    assert claimed
    gen = claimed["lease_generation"]
    ref = tmp_path / "result.json"
    ref.write_text("{}", encoding="utf-8")
    assert store.complete(task["task_id"], "w", gen, str(ref))
    assert store.get(task["task_id"])["status"] == "completed"
    store.recover_orphaned_tasks()
    assert store.get(task["task_id"])["status"] == "completed"


# ── Test: idempotent recovery ────────────────────────────────────────


def test_recovery_is_idempotent(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="idempotent")
    claimed = store.claim("dead", lease_seconds=1)
    assert claimed
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    first = store.recover_orphaned_tasks()
    second = store.recover_orphaned_tasks()
    assert first["leased_recovered"] >= 1
    assert second["leased_recovered"] == 0


# ── Test: dedup unblocks after recovery ─────────────────────────────


def test_recovered_task_dedup_unblocks_enqueue(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue(
        "pulse_check", {"scheduled": True}, idempotency_key="dedup-test"
    )
    claimed = store.claim("dead", lease_seconds=1)
    assert claimed
    store.start(task["task_id"], "dead", claimed["lease_generation"])
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    store.recover_orphaned_tasks()
    fresh = store.enqueue(
        "pulse_check", {"scheduled": True}, idempotency_key="dedup-fresh"
    )
    assert fresh is not None
    recovered = store.get(task["task_id"])
    assert recovered["status"] in ("completed", "completion_uncertain")


# ── Test: retry_after respected by claim ────────────────────────────


def test_retry_wait_not_claimable_until_retry_after(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="retry-timer", max_attempts=3)
    claimed = store.claim("w", lease_seconds=30)
    assert claimed
    store.fail(
        task["task_id"],
        "w",
        claimed["lease_generation"],
        "err",
        base_delay_seconds=3600,
    )
    store.recover_orphaned_tasks()
    assert store.claim("other") is None


# ── Test: lock file prevents recovery ──────────────────────────────


def test_dead_lock_allows_recovery(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    task = store.enqueue("work", {}, idempotency_key="dead-lock")
    claimed = store.claim("dead-worker", lease_seconds=30)
    assert claimed
    _expire_lease(tmp_path / "tasks.db", task["task_id"])
    lock = _make_lock(tmp_path / "tasks.db", _dead_pid())
    result = store.recover_orphaned_tasks(lock_file=lock)
    assert result["leased_recovered"] >= 1


# ── End-to-end: full scenario ─────────────────────────────────────


def test_end_to_end_recovery_scenario(tmp_path: Path):
    db = tmp_path / "tasks.db"
    store = AutonomousTaskStore(db)
    dead_worker = "dead-worker"

    # 1. Crear tareas en todos los estados relevantes
    t_leased = store.enqueue(
        "pulse_check", {"scheduled": True}, idempotency_key="e2e-leased"
    )
    c1 = store.claim(dead_worker, lease_seconds=30)
    assert c1 and c1["task_id"] == t_leased["task_id"]
    _expire_lease(db, t_leased["task_id"])

    t_running = store.enqueue(
        "experimental_neuron_activity", {}, idempotency_key="e2e-running"
    )
    c2 = store.claim(dead_worker, lease_seconds=30)
    assert c2
    store.start(t_running["task_id"], dead_worker, c2["lease_generation"])
    _expire_lease(db, t_running["task_id"])

    t_retry = store.enqueue(
        "work", {"x": 1}, idempotency_key="e2e-retry", max_attempts=3
    )
    c3 = store.claim(dead_worker, lease_seconds=30)
    assert c3
    store.fail(
        t_retry["task_id"],
        dead_worker,
        c3["lease_generation"],
        "transient",
        base_delay_seconds=3600,
    )

    t_deferred = store.enqueue("research", {"q": "?"}, idempotency_key="e2e-deferred")
    c4 = store.claim(dead_worker, lease_seconds=30)
    assert c4
    store.defer(
        t_deferred["task_id"],
        dead_worker,
        c4["lease_generation"],
        "backpressure",
        delay_seconds=3600,
    )

    t_completed = store.enqueue("pulse_check", {}, idempotency_key="e2e-completed")
    c5 = store.claim(dead_worker, lease_seconds=30)
    assert c5
    ref = tmp_path / "ok.json"
    ref.write_text("{}", encoding="utf-8")
    assert store.complete(
        t_completed["task_id"], dead_worker, c5["lease_generation"], str(ref)
    )

    # 2. Simular muerte del worker: sin lock file
    lock = _make_lock(db, _dead_pid())

    # 3. Ejecutar recovery
    result = store.recover_orphaned_tasks(lock_file=lock)
    assert result["status"] == "recovered"
    assert result["leased_recovered"] >= 1
    assert result["running_uncertain"] >= 1
    assert result["retry_wait_preserved"] >= 1
    assert result["deferred_preserved"] >= 1

    # 4. Verificar tratamiento diferencial
    assert store.get(t_leased["task_id"])["status"] == "recovered"
    assert store.get(t_running["task_id"])["status"] == "completion_uncertain"
    assert store.get(t_retry["task_id"])["status"] == "retry_wait"
    assert store.get(t_deferred["task_id"])["status"] == "deferred"
    assert store.get(t_completed["task_id"])["status"] == "completed"

    # 5. Nuevo worker reclama solo tareas reclamables
    new_worker = "fresh-worker"
    claimed = store.claim(new_worker)
    assert claimed is not None
    assert claimed["task_id"] == t_leased["task_id"]
    assert claimed["status"] == "leased"

    # 6. retry_wait y deferred no son reclamables
    assert store.claim(new_worker) is None

    # 7. Fencing: old worker no puede completar
    late_ref = tmp_path / "late.json"
    late_ref.write_text("{}", encoding="utf-8")
    assert not store.complete(
        t_running["task_id"], dead_worker, c2["lease_generation"], str(late_ref)
    )

    # 8. New worker completa una vez
    assert store.complete(
        claimed["task_id"], new_worker, claimed["lease_generation"], str(ref)
    )
    assert store.get(claimed["task_id"])["status"] == "completed"


# ── Test: full return dict ──────────────────────────────────────────


def test_return_dict_contains_all_keys(tmp_path: Path):
    store = AutonomousTaskStore(tmp_path / "tasks.db")
    result = store.recover_orphaned_tasks()
    for key in (
        "status",
        "leased_recovered",
        "running_recovered",
        "running_uncertain",
        "retry_wait_preserved",
        "deferred_preserved",
        "uncertain_completed",
        "uncertain_quarantined",
        "fencing_invalidated",
    ):
        assert key in result, f"missing key: {key}"
