"""Integración workers + LearningPipeline + memoria semántica."""

from __future__ import annotations

from pathlib import Path

from triade.learning.pipeline import LearningPipeline
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


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
