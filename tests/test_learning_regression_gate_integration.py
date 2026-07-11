from __future__ import annotations

from pathlib import Path

import pytest

from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.evidence_bridge import LearningEvidenceBridge
from triade.regression import MetricPolicy


def make_run(evaluation_id: str, subject_id: str, scores: dict[str, float]) -> EvaluationRun:
    results = tuple(
        MetricResult(
            case_id=case_id,
            score=score,
            passed=score >= 0.5,
            actual=score,
            expected=1.0,
        )
        for case_id, score in scores.items()
    )
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id="learning-critical",
        suite_version="1.0.0",
        subject_id=subject_id,
        results=results,
        aggregate_score=sum(scores.values()) / len(scores),
        created_at="2026-07-11T00:00:00+00:00",
    )


def attach_improvement(
    bridge: LearningEvidenceBridge,
    candidate_id: str,
    subject_id: str,
    baseline: EvaluationRun,
    candidate: EvaluationRun,
) -> None:
    bridge.record_comparison(
        candidate_id,
        baseline=baseline,
        candidate=candidate,
        comparison=EvaluationComparison(
            baseline_evaluation_id=baseline.evaluation_id,
            candidate_evaluation_id=candidate.evaluation_id,
            baseline_score=baseline.aggregate_score,
            candidate_score=candidate.aggregate_score,
            absolute_delta=candidate.aggregate_score - baseline.aggregate_score,
            percent_delta=(candidate.aggregate_score - baseline.aggregate_score)
            / baseline.aggregate_score,
            improved_cases=tuple(candidate_scores for candidate_scores in ("quality",)),
            degraded_cases=(),
            critical_regressions=(),
            decision="improved",
        ),
    )


def test_required_regression_report_blocks_when_missing(tmp_path: Path) -> None:
    bridge = LearningEvidenceBridge(tmp_path / "triade.db")
    candidate_id = "candidate-required"
    subject_id = "subject-required"
    baseline = make_run("baseline-required", subject_id, {"quality": 0.6, "identity": 1.0})
    candidate = make_run("candidate-required-eval", subject_id, {"quality": 0.8, "identity": 1.0})

    bridge.declare_hypothesis(
        candidate_id,
        hypothesis="mejorar calidad sin degradar identidad",
        capability="learning",
        subject_id=subject_id,
        require_regression=True,
    )
    attach_improvement(bridge, candidate_id, subject_id, baseline, candidate)

    with pytest.raises(ValueError, match="no existe reporte"):
        bridge.require_improvement(candidate_id)


def test_pass_report_allows_learning_promotion(tmp_path: Path) -> None:
    bridge = LearningEvidenceBridge(tmp_path / "triade.db")
    candidate_id = "candidate-pass"
    subject_id = "subject-pass"
    baseline = make_run("baseline-pass", subject_id, {"quality": 0.6, "identity": 1.0})
    candidate = make_run("candidate-pass-eval", subject_id, {"quality": 0.8, "identity": 1.0})

    bridge.declare_hypothesis(
        candidate_id,
        hypothesis="mejorar calidad sin degradar identidad",
        capability="learning",
        subject_id=subject_id,
        require_regression=True,
    )
    attach_improvement(bridge, candidate_id, subject_id, baseline, candidate)
    report = bridge.regression_gate.evaluate(
        report_id="report-pass",
        candidate_id=candidate_id,
        capability="learning",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity", severity="critical"),),
    )
    bridge.record_regression_report(candidate_id, report)

    evidence = bridge.require_improvement(candidate_id)

    assert evidence["decision"] == "improved"
    assert evidence["regression_report"]["decision"] == "pass"
    assert evidence["regression_quarantined"] is False


def test_failed_regression_report_blocks_and_quarantines(tmp_path: Path) -> None:
    bridge = LearningEvidenceBridge(tmp_path / "triade.db")
    candidate_id = "candidate-fail"
    subject_id = "subject-fail"
    baseline = make_run("baseline-fail", subject_id, {"quality": 0.6, "identity": 1.0})
    candidate = make_run("candidate-fail-eval", subject_id, {"quality": 0.9, "identity": 0.7})

    bridge.declare_hypothesis(
        candidate_id,
        hypothesis="mejorar calidad sin degradar identidad",
        capability="learning",
        subject_id=subject_id,
        require_regression=True,
    )
    attach_improvement(bridge, candidate_id, subject_id, baseline, candidate)
    report = bridge.regression_gate.evaluate(
        report_id="report-fail",
        candidate_id=candidate_id,
        capability="learning",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity", severity="critical"),),
    )
    bridge.record_regression_report(candidate_id, report)

    with pytest.raises(ValueError, match="Regression Gate bloquea"):
        bridge.require_improvement(candidate_id)

    evidence = bridge.get(candidate_id)
    assert evidence is not None
    assert evidence["regression_quarantined"] is True


def test_report_must_match_declared_capability(tmp_path: Path) -> None:
    bridge = LearningEvidenceBridge(tmp_path / "triade.db")
    candidate_id = "candidate-capability"
    subject_id = "subject-capability"
    baseline = make_run("baseline-capability", subject_id, {"identity": 1.0})
    candidate = make_run("candidate-capability-eval", subject_id, {"identity": 1.0})

    bridge.declare_hypothesis(
        candidate_id,
        hypothesis="proteger identidad",
        capability="learning",
        subject_id=subject_id,
        require_regression=True,
    )
    report = bridge.regression_gate.evaluate(
        report_id="report-other-capability",
        candidate_id=candidate_id,
        capability="memory",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity", severity="critical"),),
    )

    with pytest.raises(ValueError, match="capacidad declarada"):
        bridge.record_regression_report(candidate_id, report)
