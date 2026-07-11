from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.runner import TriadeRunner
from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_store import SemanticMemoryStore
from triade.workers.worker_loop import WorkerLoop


def _identity_rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT key, value, category, confidence FROM identity_core ORDER BY key").fetchall()


def _attach_improved_evidence(pipe: LearningPipeline, cid: str) -> None:
    subject = f"candidate:{cid}"
    pipe.evidence_bridge.declare_hypothesis(
        cid,
        hypothesis="La observabilidad consolidada mejora una capacidad medible.",
        capability="learning_observability",
        subject_id=subject,
    )
    baseline = EvaluationRun(
        evaluation_id=f"base-{cid}",
        suite_id="learning-observability",
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult("observability-case", 0.0, False, False, True),),
        aggregate_score=0.0,
        created_at="2026-07-11T00:00:00Z",
    )
    candidate = EvaluationRun(
        evaluation_id=f"candidate-{cid}",
        suite_id="learning-observability",
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult("observability-case", 1.0, True, True, True),),
        aggregate_score=1.0,
        created_at="2026-07-11T00:00:01Z",
    )
    comparison = EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=0.0,
        candidate_score=1.0,
        absolute_delta=1.0,
        percent_delta=None,
        improved_cases=("observability-case",),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )
    pipe.evidence_bridge.record_comparison(
        cid,
        baseline=baseline,
        candidate=candidate,
        comparison=comparison,
        artifact_ref=f"runs/learning_evidence/{cid}",
    )


def test_end_to_end_learning_consolidates_without_skipping_gates(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    runner = TriadeRunner(db_path=db_path, runs_dir=runs_dir, use_ollama=False)
    identity_before = _identity_rows(db_path)

    run = runner.run(
        "Audita aprendizaje controlado para observabilidad e2e.",
        source="pytest",
        propose_neurons=False,
    )
    run_path = Path(run["run_path"])
    assert run_path.exists()
    assert (run_path / "output.json").exists()
    assert (run_path / "memory_diff.json").exists()
    assert (run_path / "CLOSED").exists()

    pipe = LearningPipeline(db_path=db_path)
    candidate = pipe.ingest(
        content="La observabilidad consolidada debe pasar por candidate evaluated verified validated_in_runs y stable.",
        source_type="document",
        source_ref="pytest:e2e-learning-observability",
        title="Observabilidad consolidada por gates",
        domain="observability",
        risk_level="low",
    )
    cid = candidate["candidate_id"]
    assert pipe.evaluate(cid)["status"] == "evaluated"
    assert pipe.verify(cid)["status"] == "verified"
    _attach_improved_evidence(pipe, cid)
    for idx in range(3):
        used = pipe.mark_used_in_run(cid, f"e2e-run-{idx}", outcome_score=0.86)
    assert used["status"] == "validated_in_runs"
    assert used["measurement_evidence"]["decision"] == "improved"

    loop = WorkerLoop(db_path=db_path, runs_dir=tmp_path / "worker-runs")
    task_dir = tmp_path / "worker-runs" / "stable-review"
    task_dir.mkdir(parents=True, exist_ok=True)
    result = loop._stable_consolidation_review(
        type("FakeTask", (), {"id": 1, "task_type": "stable_consolidation_review", "to_dict": lambda self: {}})(),
        "worker-e2e-stable",
        task_dir,
        type("FakeConfig", (), {"task_timeout": 30.0, "dry_run": False})(),
    )

    assert result["status"] == "completed"
    assert result["stable_memory_written"] is True
    assert cid in {item["candidate_id"] for item in result["consolidated"]}
    consolidated = pipe.get_candidate(cid)
    assert consolidated["status"] == "consolidated"

    documents = SemanticMemoryStore(db_path=db_path).list_documents(limit=20)
    stable_docs = [doc for doc in documents if doc.get("status") == "stable" and doc.get("metadata", {}).get("learning_candidate_id") == cid]
    assert stable_docs
    assert "observabilidad consolidada" in stable_docs[0]["content"].lower()
    assert stable_docs[0]["metadata"]["measurement_evidence"]["decision"] == "improved"
    assert _identity_rows(db_path) == identity_before
