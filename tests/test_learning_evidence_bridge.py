from __future__ import annotations

import pytest

from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.evidence_bridge import LearningEvidenceBridge


def _run(evaluation_id: str, subject_id: str, score: float) -> EvaluationRun:
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id="learning-suite",
        suite_version="1.0.0",
        subject_id=subject_id,
        results=(
            MetricResult(
                case_id="case-1",
                score=score,
                passed=score == 1.0,
                actual=score,
                expected=1.0,
            ),
        ),
        aggregate_score=score,
        created_at="2026-07-11T00:00:00Z",
    )


def test_bridge_requires_declared_hypothesis(tmp_path) -> None:
    bridge = LearningEvidenceBridge(tmp_path / "triade.db")
    baseline = _run("base", "subject", 0.5)
    candidate = _run("candidate", "subject", 1.0)
    comparison = EvaluationComparison(
        baseline_evaluation_id="base",
        candidate_evaluation_id="candidate",
        baseline_score=0.5,
        candidate_score=1.0,
        absolute_delta=0.5,
        percent_delta=100.0,
        improved_cases=("case-1",),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )

    with pytest.raises(ValueError, match="hipótesis"):
        bridge.record_comparison(
            "learn-1",
            baseline=baseline,
            candidate=candidate,
            comparison=comparison,
        )


def test_bridge_persists_improved_evidence(tmp_path) -> None:
    bridge = LearningEvidenceBridge(tmp_path / "triade.db")
    bridge.declare_hypothesis(
        "learn-1",
        hypothesis="La normalización reduce errores",
        capability="normalization",
        subject_id="learning-pipeline",
    )
    baseline = _run("base", "learning-pipeline", 0.0)
    candidate = _run("candidate", "learning-pipeline", 1.0)
    comparison = EvaluationComparison(
        baseline_evaluation_id="base",
        candidate_evaluation_id="candidate",
        baseline_score=0.0,
        candidate_score=1.0,
        absolute_delta=1.0,
        percent_delta=None,
        improved_cases=("case-1",),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )

    stored = bridge.record_comparison(
        "learn-1",
        baseline=baseline,
        candidate=candidate,
        comparison=comparison,
        artifact_ref="runs/learning_evidence/learn-1",
    )

    assert stored["decision"] == "improved"
    assert stored["comparison"]["absolute_delta"] == 1.0
    assert bridge.require_improvement("learn-1")["artifact_ref"].endswith("learn-1")


def test_bridge_blocks_neutral_regressed_and_wrong_subject(tmp_path) -> None:
    bridge = LearningEvidenceBridge(tmp_path / "triade.db")
    bridge.declare_hypothesis(
        "learn-2",
        hypothesis="Mejora esperada",
        capability="cap",
        subject_id="subject-a",
    )
    baseline = _run("base", "subject-a", 1.0)
    candidate = _run("candidate", "subject-a", 1.0)
    neutral = EvaluationComparison(
        baseline_evaluation_id="base",
        candidate_evaluation_id="candidate",
        baseline_score=1.0,
        candidate_score=1.0,
        absolute_delta=0.0,
        percent_delta=0.0,
        improved_cases=(),
        degraded_cases=(),
        critical_regressions=(),
        decision="neutral",
    )
    bridge.record_comparison("learn-2", baseline=baseline, candidate=candidate, comparison=neutral)

    with pytest.raises(ValueError, match="no demuestra mejora"):
        bridge.require_improvement("learn-2")

    wrong_subject = _run("candidate-2", "subject-b", 1.0)
    invalid = EvaluationComparison(
        baseline_evaluation_id="base",
        candidate_evaluation_id="candidate-2",
        baseline_score=1.0,
        candidate_score=1.0,
        absolute_delta=0.0,
        percent_delta=0.0,
        improved_cases=(),
        degraded_cases=(),
        critical_regressions=(),
        decision="neutral",
    )
    with pytest.raises(ValueError, match="subject_id"):
        bridge.record_comparison(
            "learn-2",
            baseline=baseline,
            candidate=wrong_subject,
            comparison=invalid,
        )
