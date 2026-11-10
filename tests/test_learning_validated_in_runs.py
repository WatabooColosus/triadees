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


def test_mark_used_in_run_multiple_uses_requires_evidence_at_promotion_gate(
    tmp_path: Path,
) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    pipe.mark_used_in_run(cid, "run-2", outcome_score=0.90)
    with pytest.raises(ValueError, match="No existe evidencia"):
        pipe.mark_used_in_run(cid, "run-3", outcome_score=0.70)
    result = pipe.get_candidate(cid)
    assert result["run_use_count"] == 2
    assert result["avg_outcome_score"] == 0.85
    assert result["status"] == "internally_checked"


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
    assert result["status"] == "internally_checked"
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
    with pytest.raises(ValueError, match="internally_checked.*validated_in_runs"):
        pipe.consolidate(cid)


def test_validate_in_run_alias(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    result = pipe.validate_in_run(cid, "run-alias-1", outcome_score=0.90)
    assert result["run_use_count"] == 1
    assert result["avg_outcome_score"] == 0.90

def test_duplicate_run_id_is_idempotent(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    first = pipe.mark_used_in_run(cid, "same-run", 0.80)
    retry = pipe.mark_used_in_run(cid, "same-run", 0.80)
    assert first["run_use_count"] == retry["run_use_count"] == 1
    assert retry["status"] == "internally_checked"
    pipe.mark_used_in_run(cid, "different-run", 0.90)
    assert pipe.get_candidate(cid)["run_use_count"] == 2


def test_conflicting_retry_does_not_overwrite_original(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    pipe.mark_used_in_run(cid, "same-run", 0.80)
    with pytest.raises(ValueError, match="ya registrado"):
        pipe.mark_used_in_run(cid, "same-run", 0.99)
    assert pipe.get_candidate(cid)["run_outcome_scores"] == "[0.8]"


def test_legacy_counter_is_preserved_separately(tmp_path: Path) -> None:
    import sqlite3

    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    with sqlite3.connect(pipe.db_path) as conn:
        conn.execute(
            "UPDATE learning_queue SET run_use_count=2, "
            "run_outcome_scores='[0.7,0.8]', avg_outcome_score=0.75 "
            "WHERE candidate_id=?", (cid,)
        )
    result = pipe.mark_used_in_run(cid, "first-traceable-run", 0.90)
    assert result["run_use_count"] == 1
    with sqlite3.connect(pipe.db_path) as conn:
        old = conn.execute(
            "SELECT run_use_count, run_outcome_scores "
            "FROM learning_candidate_legacy_run_counts WHERE candidate_id=?",
            (cid,),
        ).fetchone()
    assert old == (2, "[0.7,0.8]")


def test_production_model_policy_is_strict_even_with_disable_override(
    tmp_path: Path, monkeypatch
) -> None:
    from triade.core import runtime_scope

    monkeypatch.setattr(runtime_scope, "is_test_runtime", lambda: False)
    monkeypatch.setenv("TRIADE_ENFORCE_MODEL_POLICY", "0")
    monkeypatch.setattr(
        "triade.learning.pipeline.check_ollama_blood",
        lambda: {"status": "degraded", "can_reason": False},
    )
    pipe = LearningPipeline(tmp_path / "no-model.db", enforce_model_policy=False)
    assert pipe.enforce_model_policy is True
    cid = pipe.ingest(
        content="Patrón con fuente para comprobar bloqueo de modelo",
        source_type="document",
        source_ref="test:model",
        domain="test",
    )["candidate_id"]
    assert pipe.evaluate(cid)["status"] == "requires_model"
    assert pipe.get_candidate(cid)["status"] == "candidate"


def test_missing_evidence_preserves_counter_and_allows_later_retry(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    pipe.mark_used_in_run(cid, "run-1", 0.80)
    pipe.mark_used_in_run(cid, "run-2", 0.90)
    with pytest.raises(ValueError, match="No existe evidencia"):
        pipe.mark_used_in_run(cid, "run-3", 0.70)
    assert pipe.get_candidate(cid)["run_use_count"] == 2
    _attach_improved_evidence(pipe, cid)
    result = pipe.mark_used_in_run(cid, "run-3", 0.70)
    assert result["run_use_count"] == 3
    assert result["status"] == "validated_in_runs"
