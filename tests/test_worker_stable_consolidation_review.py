"""Tests de stable_consolidation_review en workers."""

from pathlib import Path

from triade.learning.pipeline import LearningPipeline
from triade.workers.worker_loop import WorkerLoop


def _setup_verified_candidates(tmp_path: Path, count: int = 3) -> list[str]:
    pipe = LearningPipeline(db_path=tmp_path / "triade.db")
    cids = []
    for i in range(count):
        cid = pipe.ingest(
            content=f"Patrón {i} verificado para revisión estable.",
            source_type="document",
            source_ref=f"test:stable-{i}",
            title=f"Patrón estable {i}",
            domain="test",
            risk_level="low",
        )["candidate_id"]
        pipe.evaluate(cid)
        pipe.verify(cid)
        for j in range(3):
            pipe.mark_used_in_run(cid, f"run-{i}-{j}", outcome_score=0.85)
        cids.append(cid)
    return cids


def test_stable_consolidation_review_consolidates_eligible(tmp_path: Path) -> None:
    cids = _setup_verified_candidates(tmp_path, 2)
    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs")
    result = loop._stable_consolidation_review(
        type("FakeTask", (), {"id": 1, "task_type": "stable_consolidation_review", "to_dict": lambda: {}})(),
        "run-test-stable",
        tmp_path / "runs" / "stable-test",
        type("FakeConfig", (), {"task_timeout": 30.0, "dry_run": False})(),
    )
    assert result["status"] == "completed"
    assert len(result["consolidated"]) >= 2
    assert result["stable_memory_written"] is True


def test_stable_consolidation_review_skips_unvalidated(tmp_path: Path) -> None:
    pipe = LearningPipeline(db_path=tmp_path / "triade.db")
    cid = pipe.ingest(
        content="Candidato verified sin uso en runs.",
        source_type="document",
        source_ref="test:no-uses",
        title="Sin usos",
        domain="test",
        risk_level="low",
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)

    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs")
    result = loop._stable_consolidation_review(
        type("FakeTask", (), {"id": 1, "task_type": "stable_consolidation_review", "to_dict": lambda: {}})(),
        "run-test-no-uses",
        tmp_path / "runs" / "no-uses-test",
        type("FakeConfig", (), {"task_timeout": 30.0, "dry_run": False})(),
    )
    assert result["status"] == "completed"
    assert len(result["consolidated"]) == 0


def test_memory_consolidation_review_marks_used(tmp_path: Path) -> None:
    pipe = LearningPipeline(db_path=tmp_path / "triade.db")
    cid = pipe.ingest(
        content="Candidato verified para tracking.",
        source_type="document",
        source_ref="test:tracking",
        title="Tracking test",
        domain="test",
        risk_level="low",
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)

    loop = WorkerLoop(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs")
    result = loop._memory_consolidation_review(
        type("FakeTask", (), {"id": 1, "task_type": "memory_consolidation_review", "to_dict": lambda: {}})(),
        "run-test-tracking",
        tmp_path / "runs" / "tracking-test",
        type("FakeConfig", (), {"task_timeout": 30.0, "dry_run": False})(),
    )
    assert result["status"] == "completed"
    assert len(result["run_tracking_updates"]) >= 1
    updated = pipe.get_candidate(cid)
    assert updated["run_use_count"] >= 1
