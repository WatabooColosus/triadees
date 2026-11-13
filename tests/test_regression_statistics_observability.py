from __future__ import annotations

from pathlib import Path

from triade.evaluation import EvaluationRun, MetricResult
from triade.regression import MetricPolicy, RegressionGate
from triade.regression.observability import RegressionObservability
from triade.regression.protection_registry import (
    CapabilityProtectionRegistry,
    ProtectionRule,
)
from triade.regression.rollback import RollbackExecutor
from triade.regression.statistics import (
    StatisticalPolicy,
    StatisticalRegressionAnalyzer,
)


def make_run(evaluation_id: str, score: float) -> EvaluationRun:
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id="critical",
        suite_version="1.0.0",
        subject_id=evaluation_id,
        results=(
            MetricResult(
                case_id="identity_core",
                score=score,
                passed=score >= 0.5,
                actual=score,
                expected=1.0,
            ),
        ),
        aggregate_score=score,
        created_at="2026-07-11T00:00:00+00:00",
    )


def test_statistics_passes_stable_candidate() -> None:
    result = StatisticalRegressionAnalyzer.compare(
        baseline_scores=(0.80, 0.81, 0.79, 0.80),
        candidate_scores=(0.82, 0.81, 0.83, 0.82),
        policy=StatisticalPolicy("quality", min_samples=3),
    )

    assert result.decision == "pass"
    assert result.mean_delta is not None and result.mean_delta > 0


def test_statistics_fails_confirmed_critical_drop() -> None:
    result = StatisticalRegressionAnalyzer.compare(
        baseline_scores=(0.90, 0.91, 0.89, 0.90),
        candidate_scores=(0.70, 0.71, 0.69, 0.70),
        policy=StatisticalPolicy("identity_core", min_samples=3, critical=True),
    )

    assert result.decision == "fail"
    assert result.confidence_high is not None and result.confidence_high < 0


def test_statistics_invalid_with_insufficient_samples() -> None:
    result = StatisticalRegressionAnalyzer.compare(
        baseline_scores=(0.9,),
        candidate_scores=(0.8,),
        policy=StatisticalPolicy("quality", min_samples=3),
    )

    assert result.decision == "invalid"


def test_observability_reports_gate_health(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    gate = RegressionGate(db_path)
    registry = CapabilityProtectionRegistry(db_path)
    registry.register(
        ProtectionRule(
            capability="learning",
            metric_id="identity_core",
            version="1.0.0",
            severity="critical",
            immutable=True,
        )
    )
    baseline = make_run("baseline", 1.0)
    candidate = make_run("candidate", 0.8)
    gate.record_stable_state("learning", baseline)
    gate.evaluate(
        report_id="report-fail",
        candidate_id="candidate-1",
        capability="learning",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity_core", severity="critical"),),
    )
    rollback = RollbackExecutor(db_path)
    rollback.plan(
        rollback_id="rollback-1",
        capability="learning",
        candidate_id="candidate-1",
        report_id="report-fail",
        target=gate.rollback_target("learning") or {},
        reason="critical regression",
        requested_by="central",
    )

    snapshot = RegressionObservability(db_path).snapshot()

    assert snapshot["status"] == "attention"
    assert snapshot["reports"]["by_decision"]["fail"] == 1
    assert snapshot["quarantine"]["active"] == 1
    assert snapshot["protections"]["immutable"] == 1
    assert snapshot["rollbacks"]["by_status"]["planned"] == 1
    assert snapshot["stable_capabilities"] == 1


def test_observability_handles_missing_database(tmp_path: Path) -> None:
    snapshot = RegressionObservability(tmp_path / "missing.db").snapshot()

    assert snapshot["status"] == "not_initialized"
