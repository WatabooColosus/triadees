from __future__ import annotations

import sqlite3

import pytest

from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.pipeline import LearningPipeline


def _evaluation(evaluation_id: str, subject_id: str, score: float) -> EvaluationRun:
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id="learning-evidence",
        suite_version="1.0.0",
        subject_id=subject_id,
        results=(
            MetricResult(
                case_id="capability-case",
                score=score,
                passed=score == 1.0,
                actual=score,
                expected=1.0,
            ),
        ),
        aggregate_score=score,
        created_at="2026-07-11T00:00:00Z",
    )


def _force_verified(pipeline: LearningPipeline, candidate_id: str) -> None:
    with sqlite3.connect(pipeline.db_path) as conn:
        conn.execute(
            "UPDATE learning_queue SET status='verified', confidence=0.9, utility=0.9 WHERE candidate_id=?",
            (candidate_id,),
        )


def _attach_improvement(pipeline: LearningPipeline, candidate_id: str) -> None:
    subject_id = f"candidate:{candidate_id}"
    pipeline.evidence_bridge.declare_hypothesis(
        candidate_id,
        hypothesis="El candidato mejora una capacidad medible",
        capability="learning_capability",
        subject_id=subject_id,
    )
    baseline = _evaluation(f"base-{candidate_id}", subject_id, 0.0)
    candidate = _evaluation(f"candidate-{candidate_id}", subject_id, 1.0)
    comparison = EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=0.0,
        candidate_score=1.0,
        absolute_delta=1.0,
        percent_delta=None,
        improved_cases=("capability-case",),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )
    pipeline.evidence_bridge.record_comparison(
        candidate_id,
        baseline=baseline,
        candidate=candidate,
        comparison=comparison,
        artifact_ref=f"runs/learning_evidence/{candidate_id}",
    )


def test_pipeline_blocks_validation_without_measurement_evidence(tmp_path) -> None:
    pipeline = LearningPipeline(db_path=tmp_path / "triade.db", enforce_model_policy=False)
    candidate = pipeline.ingest(
        "Patrón operativo suficientemente detallado para evaluación.",
        source_type="repo",
        source_ref="repo://triade/test",
        domain="testing",
    )
    candidate_id = candidate["candidate_id"]
    _force_verified(pipeline, candidate_id)

    pipeline.mark_used_in_run(candidate_id, "run-1", 0.9)
    pipeline.mark_used_in_run(candidate_id, "run-2", 0.9)
    with pytest.raises(ValueError, match="No existe evidencia"):
        pipeline.mark_used_in_run(candidate_id, "run-3", 0.9)

    stored = pipeline.get_candidate(candidate_id)
    assert stored is not None
    assert stored["status"] == "verified"
    assert stored["run_use_count"] == 3
    assert stored["measurement_evidence"] is None


def test_pipeline_promotes_only_with_improved_evidence(tmp_path) -> None:
    pipeline = LearningPipeline(db_path=tmp_path / "triade.db", enforce_model_policy=False)
    candidate = pipeline.ingest(
        "Patrón operativo suficientemente detallado para evaluación.",
        source_type="repo",
        source_ref="repo://triade/test",
        domain="testing",
    )
    candidate_id = candidate["candidate_id"]
    _force_verified(pipeline, candidate_id)
    _attach_improvement(pipeline, candidate_id)

    pipeline.mark_used_in_run(candidate_id, "run-1", 0.9)
    pipeline.mark_used_in_run(candidate_id, "run-2", 0.9)
    promoted = pipeline.mark_used_in_run(candidate_id, "run-3", 0.9)

    assert promoted["status"] == "validated_in_runs"
    assert promoted["measurement_evidence"]["decision"] == "improved"
    assert promoted["verification_notes"]["validated_in_runs"]["measurement_decision"] == "improved"


def test_pipeline_blocks_neutral_evidence(tmp_path) -> None:
    pipeline = LearningPipeline(db_path=tmp_path / "triade.db", enforce_model_policy=False)
    candidate = pipeline.ingest(
        "Patrón operativo suficientemente detallado para evaluación.",
        source_type="repo",
        source_ref="repo://triade/test",
        domain="testing",
    )
    candidate_id = candidate["candidate_id"]
    _force_verified(pipeline, candidate_id)
    subject_id = f"candidate:{candidate_id}"
    pipeline.evidence_bridge.declare_hypothesis(
        candidate_id,
        hypothesis="La capacidad debería mejorar",
        capability="learning_capability",
        subject_id=subject_id,
    )
    baseline = _evaluation(f"base-{candidate_id}", subject_id, 1.0)
    candidate_run = _evaluation(f"candidate-{candidate_id}", subject_id, 1.0)
    comparison = EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate_run.evaluation_id,
        baseline_score=1.0,
        candidate_score=1.0,
        absolute_delta=0.0,
        percent_delta=0.0,
        improved_cases=(),
        degraded_cases=(),
        critical_regressions=(),
        decision="neutral",
    )
    pipeline.evidence_bridge.record_comparison(
        candidate_id,
        baseline=baseline,
        candidate=candidate_run,
        comparison=comparison,
    )

    pipeline.mark_used_in_run(candidate_id, "run-1", 0.9)
    pipeline.mark_used_in_run(candidate_id, "run-2", 0.9)
    with pytest.raises(ValueError, match="decision=neutral"):
        pipeline.mark_used_in_run(candidate_id, "run-3", 0.9)

    assert pipeline.get_candidate(candidate_id)["status"] == "verified"
