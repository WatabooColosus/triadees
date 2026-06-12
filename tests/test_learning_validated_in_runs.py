"""Tests del estado validated_in_runs en LearningPipeline."""

from pathlib import Path

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


def test_mark_used_in_run_increments_count(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    result = pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    assert result["run_use_count"] == 1
    assert result["avg_outcome_score"] == 0.80


def test_mark_used_in_run_multiple_uses(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    pipe.mark_used_in_run(cid, "run-2", outcome_score=0.90)
    result = pipe.mark_used_in_run(cid, "run-3", outcome_score=0.70)
    assert result["run_use_count"] == 3
    assert result["avg_outcome_score"] == 0.80


def test_auto_validates_after_min_uses(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    pipe.mark_used_in_run(cid, "run-2", outcome_score=0.85)
    result = pipe.mark_used_in_run(cid, "run-3", outcome_score=0.75)
    assert result["status"] == "validated_in_runs"
    assert result["run_use_count"] == 3


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
    pipe.mark_used_in_run(cid, "run-1", outcome_score=0.80)
    import pytest
    with pytest.raises(ValueError, match="run_uses"):
        pipe.consolidate(cid, approved_by="test")


def test_consolidate_requires_min_score(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    for i in range(5):
        pipe.mark_used_in_run(cid, f"run-{i}", outcome_score=0.50)
    import pytest
    with pytest.raises(ValueError, match="avg_outcome_score"):
        pipe.consolidate(cid, approved_by="test")


def test_consolidate_works_with_sufficient_evidence(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
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
    import pytest
    with pytest.raises(ValueError, match="verified.*validated_in_runs"):
        pipe.consolidate(cid)


def test_validate_in_run_alias(tmp_path: Path) -> None:
    pipe = _pipe(tmp_path)
    cid = _verified_candidate(pipe)
    result = pipe.validate_in_run(cid, "run-alias-1", outcome_score=0.90)
    assert result["run_use_count"] == 1
    assert result["avg_outcome_score"] == 0.90
