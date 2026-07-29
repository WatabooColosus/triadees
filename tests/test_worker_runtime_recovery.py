import os

from triade.workers.contracts import WorkerRunConfig
from triade.workers.state_store import WorkerStateStore


def test_stale_lock_and_duplicate_queue_are_recovered(tmp_path):
    db = tmp_path / "triade.db"
    lock = tmp_path / "worker.lock"
    lock.write_text("99999999", encoding="utf-8")
    store = WorkerStateStore(db)
    store.create_worker_run("old-worker", WorkerRunConfig(), tmp_path / "artifacts")
    for _ in range(3):
        store.enqueue_task("experimental_neuron_activity", {"neuron_id": 7})
    result = store.recover_interrupted_runtime(lock)
    assert result["status"] == "recovered"
    assert result["deduplicated"] == 2
    assert not lock.exists()
    assert store.get_worker_run("old-worker")["status"] == "interrupted"
    assert store.status()["task_counts"] == {"pending": 1, "skipped": 2}


def test_live_lock_is_never_removed(tmp_path):
    db = tmp_path / "triade.db"
    lock = tmp_path / "worker.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    result = WorkerStateStore(db).recover_interrupted_runtime(lock)
    assert result["status"] == "live_owner"
    assert lock.exists()
