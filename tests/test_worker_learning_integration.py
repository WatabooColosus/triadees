"""Integración workers + LearningPipeline + memoria semántica."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.learning.pipeline import LearningPipeline
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def test_worker_reviews_learning_and_marks_verified_as_used_in_run(tmp_path: Path) -> None:
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

    loop = WorkerLoop(db_path=db_path, runs_dir=tmp_path / "runs", lock_file=tmp_path / "lock", stop_file=tmp_path / "stop")
    result = loop.run(WorkerRunConfig(max_iterations=1, sleep_seconds=0, once=True, runs_dir=str(tmp_path / "runs"), lock_file=str(tmp_path / "lock"), stop_file=str(tmp_path / "stop")))

    updated = pipe.get_candidate(candidate["candidate_id"])
    assert result["status"] == "completed"
    assert updated["status"] == "verified"
    assert int(updated["run_use_count"] or 0) >= 1
