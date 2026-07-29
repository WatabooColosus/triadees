from __future__ import annotations

from pathlib import Path

from triade.learning.validation import (
    LearningValidationReceipt,
    LearningValidationService,
)


def _candidate(**overrides) -> LearningValidationReceipt:
    values = {
        "learning_id": "learn-1", "status": "regression_check_pending",
        "hypothesis": "change improves metric", "producer_id": "trainer",
        "baseline_ref": "baseline.json", "evaluator_id": "independent-evaluator",
        "evaluation_set_ref": "held-out.json", "before_score": 0.5,
        "after_score": 0.7, "application_ref": "run-after.json",
        "rollback_ref": "rollback.json", "rollback_verified": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    values.update(overrides)
    return LearningValidationReceipt.model_validate(values)


def test_observation_is_not_learning(tmp_path: Path) -> None:
    assert LearningValidationService(tmp_path / "db.sqlite").observe().status == "observed"


def test_hypothesis_is_not_learning(tmp_path: Path) -> None:
    receipt = LearningValidationService(tmp_path / "db.sqlite").hypothesize(
        "possible improvement", producer_id="trainer"
    )
    assert receipt.status == "hypothesis_created"


def test_evaluation_without_application_is_not_learning(tmp_path: Path) -> None:
    service = LearningValidationService(tmp_path / "db.sqlite")
    result = service.assess(_candidate(application_ref=None))
    assert result.status == "evaluated"


def test_application_without_improvement_is_rejected(tmp_path: Path) -> None:
    service = LearningValidationService(tmp_path / "db.sqlite")
    result = service.assess(_candidate(after_score=0.4))
    assert result.status == "rejected"


def test_regression_blocks_consolidation(tmp_path: Path) -> None:
    service = LearningValidationService(tmp_path / "db.sqlite")
    result = service.assess(_candidate(regression_critical=True))
    assert result.status == "rejected"


def test_validated_learning_requires_all_gates(tmp_path: Path) -> None:
    service = LearningValidationService(tmp_path / "db.sqlite")
    result = service.assess(_candidate())
    assert result.status == "validated"
    assert result.evaluator_id != result.producer_id


def test_failed_learning_rolls_back(tmp_path: Path) -> None:
    service = LearningValidationService(tmp_path / "db.sqlite")
    called = 0

    def rollback() -> bool:
        nonlocal called
        called += 1
        return True

    result = service.assess(_candidate(after_score=0.1), rollback=rollback)
    assert called == 1
    assert result.status == "rolled_back"
    assert result.rollback_verified
