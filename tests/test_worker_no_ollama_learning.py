"""No-Ollama learning contracts: allow deterministic work, never invent inference.

All executions use a synthetic temporary database and a synthetic Blood report.
"""
from __future__ import annotations

from pathlib import Path

from triade.workers.contracts import WorkerRunConfig, WorkerTask
from triade.workers.worker_loop import WorkerLoop


def no_blood() -> dict:
    return {
        "status": "degraded_no_ollama",
        "ok": False,
        "ollama_ok": False,
        "reasoning_model": None,
        "embedding_model": None,
        "can_reason": False,
        "can_embed": False,
        "degraded_components": ["worker_cycle", "learning_evaluation"],
    }


def execute(tmp_path: Path, monkeypatch, task: WorkerTask, *, dry_run: bool = False) -> dict:
    import triade.workers.worker_loop as worker_module

    monkeypatch.setattr(worker_module, "check_ollama_blood", no_blood)
    loop = WorkerLoop(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )
    config = WorkerRunConfig(
        dry_run=dry_run,
        runs_dir=str(tmp_path / "runs"),
        lock_file=str(tmp_path / "lock"),
        stop_file=str(tmp_path / "stop"),
    )
    return loop._execute_task(task, "synthetic-run", tmp_path / "runs", config)


def test_learning_observation_can_close_without_model(tmp_path, monkeypatch):
    result = execute(
        tmp_path,
        monkeypatch,
        WorkerTask(
            task_type="central_learning_observation",
            payload={
                "source_run_id": "test-no-blood",
                "message": "¿Qué hora es?",
                "response": "No tengo reloj.",
                "domain": "conversation",
            },
        ),
    )
    assert result["status"] == "completed"
    assert result["effect"] == "learning_declined"
    assert result["stable_memory_written"] is False


def test_unmeasurable_learning_evidence_closes_without_model(tmp_path, monkeypatch):
    result = execute(
        tmp_path,
        monkeypatch,
        WorkerTask(task_type="learning_evidence_generation", payload={}),
    )
    assert result["status"] == "completed"
    assert result["effect"] == "no_op"
    assert result["skipped_reason"] == "sin_candidate_id"
    assert result["stable_memory_written"] is False


def test_model_dependent_work_remains_blocked_without_model(tmp_path, monkeypatch):
    result = execute(
        tmp_path,
        monkeypatch,
        WorkerTask(task_type="goal_research", payload={"topic": "synthetic test"}),
    )
    assert result["status"] == "blocked"
    assert result["ollama_blood_status"] == "degraded_no_ollama"


def test_dry_run_of_model_task_does_not_require_model(tmp_path, monkeypatch):
    result = execute(
        tmp_path,
        monkeypatch,
        WorkerTask(
            task_type="neuron_candidate_formation",
            payload={
                "admission_event_id": 42,
                "admission_phase": "training",
                "correlation_id": "synthetic-transition",
            },
        ),
        dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert result["would_execute"] is True
