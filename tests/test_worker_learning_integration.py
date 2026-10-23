"""Integración workers + LearningPipeline + memoria semántica."""

from __future__ import annotations

import json
from pathlib import Path

from triade.learning.pipeline import LearningPipeline
from triade.runtime.task_artifacts import _io_path
from triade.workers.contracts import WorkerRunConfig, WorkerTask
from triade.workers.worker_loop import WorkerLoop
from triade.workers.task_queue import WorkerTaskQueue


def test_worker_reviews_learning_and_marks_verified_as_used_in_run(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "triade.db"
    pipe = LearningPipeline(db_path=db_path)
    candidate = pipe.ingest(
        content="Aprendizaje verificable con suficiente contenido para utilidad y confianza dentro del worker.",
        source_type="conversation",
        source_ref="run:test-worker-learning",
        title="Aprendizaje worker",
        domain="workers",
        risk_level="low",
    )

    # Test the worker review handler deterministically, independently from
    # unrelated scheduled maintenance tasks and their per-cycle CPU budget.
    # MissionPlanner's automatic discovery is verified separately in
    # test_mission_planner.py::test_plan_pending_learning.
    WorkerTaskQueue(db_path).enqueue(
        "pending_learning_review",
        payload={"candidate_id": candidate["candidate_id"], "source": "test-worker"},
        priority=0,
    )
    loop = WorkerLoop(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )
    result = loop.run(
        WorkerRunConfig(
            max_iterations=1,
            sleep_seconds=0,
            once=True,
            runs_dir=str(tmp_path / "runs"),
            lock_file=str(tmp_path / "lock"),
            stop_file=str(tmp_path / "stop"),
        )
    )

    updated = pipe.get_candidate(candidate["candidate_id"])
    # El mensaje incluye los errores a propósito. Este test falló en CI con
    # concurrencia activa 3 de 3 veces, y `assert 'completed_with_errors' ==
    # 'completed'` no decía **qué** había fallado: hubo que adivinar entre CPU,
    # Ollama y versión de Python sin ningún dato. Un fallo que no se explica a sí
    # mismo cuesta una ronda entera de CI por hipótesis.
    assert result["status"] == "completed", (
        f"status={result['status']} errores={result.get('errors')} "
        f"completadas={result.get('tasks_completed')} "
        f"bloqueadas={result.get('tasks_blocked')} "
        f"concurrencia={result.get('concurrency')}"
    )
    assert updated["status"] == "internally_checked"
    assert int(updated["run_use_count"] or 0) == 0


def test_learning_review_publishes_receipt_on_long_windows_path(tmp_path):
    loop = WorkerLoop(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )
    parent = tmp_path / "artifacts"
    task_dir = parent / ("x" * max(1, 241 - len(str(parent)) - 1))
    task_dir.mkdir(parents=True)
    result = loop._pending_learning_review(
        WorkerTask(task_type="pending_learning_review"),
        "long-path-review",
        task_dir,
        WorkerRunConfig(),
    )
    artifact = Path(result["artifact_ref"])
    assert len(str(artifact)) > 260
    assert (
        json.loads(_io_path(artifact).read_text(encoding="utf-8"))["status"]
        == "completed"
    )
