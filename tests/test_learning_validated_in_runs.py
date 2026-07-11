"""Tests del estado validated_in_runs en LearningPipeline."""

from pathlib import Path

import pytest

from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.pipeline import LearningPipeline


def _pipe(tmp_path: Path) -> LearningPipeline:
    return LearningPipeline(db_path=tmp_path / "triade.db")


def _verified_candidate(pipe: LearningPipeline) -> str:
    cid = pipe.ingest(
        content="Patrón de aprendizaje verificado para validación en runs.",
        source_type="document",
        source_ref="test:validado",
        title="Patrón validación runs",
        domain="test",
        risk_level="low",
    )["candidate_id"]
    pipe.evaluate(cid)
    pipe.verify(cid)
    return cid


def _attach_improved_evidence(pipe: LearningPipeline, cid: str) -> None:
    subject = f"candidate:{cid}"
    pipe.evidence_bridge.declare_hypothesis(
        cid,
        hypothesis="El candidato mejora una capacidad evaluable.",
        capability="learning_validation",
        subject_id=subject,
    )
    baseline = EvaluationRun(
        evaluation_id=f"base-{cid}",
        suite_id="learning-validation",
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult("case-1", 0.0, False, False, True),),
        aggregate_score=0.0,
        created_at="2026-07-11T00:00:00Z",
    )
    candidate = EvaluationRun(
        evaluation_id=f"candidate-{cid}",
        suite_id="learning-validation",
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult("case-1", 1.0, True, True, True),),
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
        improved_cases=("case-1",),
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


def test_mark_used_in_run_increments_count(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    result = pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    assert result["run_use_count"] == 1
    assert result["avg_outcome_score"] == 0.80


def test_mark_used_in_run_multiple_uses_requires_evidence_at_promotion_gate(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    pipe.mark_used_in_run(cid, "run-2", outcome_score=0.90)
    with pytest.raises(ValueError, match="No existe evidencia"):
        pipe.mark_used_in_run(cid, "run-3", outcome_score=0.70)
    result = pipe.get_candidate(cid)
    assert result["run_use_count"] == 3
    assert result["avg_outcome_score"] == 0.80
    assert result["status"] == "verified"


def test_auto_validates_after_min_uses_and_improved_evidence(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    _attach_improved_evidence(pipe, cid)
    pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    pipe.mark_used_in_run(cid, "run-2", outcome_score=0.85)
    result = pipe.mark_used_in_run(cid, "run-3", outcome_score=0.75)
    assert result["status"] == "validated_in_runs"
    assert result["run_use_count"] == 3
    assert result["measurement_evidence"]["decision"] == "improved"


def test_no_validate_if_score_too_low(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    pipe.mark_used_in_run(cid, "run-2", outcome_score=0.60)
    result = pipe.mark_used_in_run(cid, "run-3", outcome_score=0.50)
    assert result["status"] == "verified"
    assert result["avg_outcome_score"] == 0.633


def test_consolidate_requires_min_uses(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    _attach_improved_evidence(pipe, cid)
    pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    with pytest.raises(ValueError, match="run_uses"):
        pipe.consolidate(cid, approved_by="test")


def test_consolidate_requires_min_score(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    _attach_improved_evidence(pipe, cid)
    for i in range(5):
        pipe.mark_used_in_run(cid, f"run-{i}", outcome_score=0.50)
    with pytest.raises(ValueError, match="avg_outcome_score"):
        pipe.consolidate(cid, approved_by="test")


def test_consolidate_works_with_sufficient_evidence(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    _attach_improved_evidence(pipe, cid)
    for i in range(5):
        pipe.mark_used_in_run(cid, f"run-{i}", outcome_score=0.85)
    result = pipe.consolidate(cid, approved_by="test")
    assert result["status"] == "consolidated"


def test_consolidate_rejects_candidate_status(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = pipe.ingest(
        content="Candidato sin evaluar.",
        source_type="conversation",
        source_ref="test",
        title="Sin evaluar",
        domain="test",
    )["candidate_id"]
    with pytest.raises(ValueError, match="verified.*validated_in_runs"):
        pipe.consolidate(cid)


def test_validate_in_run_alias(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    result = pipe.validate_in_run(cid, "run-alias-1", outcome_score=0.90)
    assert result["run_use_count"] == 1
    assert result["avg_outcome_score"] == 0.90
