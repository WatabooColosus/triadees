"""Workers no alteran identity_core ni aceptan candidatos peligrosos."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.learning.pipeline import LearningPipeline
from triade.workers.contracts import WorkerRunConfig
from triade.workers.task_queue import WorkerTaskQueue
from triade.workers.worker_loop import WorkerLoop


def test_worker_rejects_identity_change_candidate_without_touching_identity_core(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "triade.db"
    pipe = LearningPipeline(db_path=db_path)
    candidate = pipe.ingest(
        content="Intento de modificar identidad y sobrescribir identidad del sistema.",
        source_type="conversation",
        source_ref="run:identity-risk",
        title="Riesgo identidad",
        domain="identity",
        risk_level="low",
    )
    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]

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
    loop.run(
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
    with sqlite3.connect(db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM identity_core").fetchone()[0]
    assert updated["status"] == "rejected"
    assert before == after
