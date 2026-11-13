from __future__ import annotations

import pytest

from triade.evaluation import (
    BenchmarkCase,
    BenchmarkSuite,
    CapabilityBaseline,
    EvaluationComparison,
    EvaluationRun,
    MetricResult,
)


def test_benchmark_suite_requires_unique_case_ids() -> None:
    case = BenchmarkCase(
        case_id="identity-1",
        capability="identity_protection",
        input_payload={"content": "modificar identidad"},
        expected="blocked",
        critical=True,
    )

    with pytest.raises(ValueError, match="duplicado"):
        BenchmarkSuite(
            suite_id="identity-protection",
            version="1.0.0",
            capability="identity_protection",
            cases=(case, case),
        )


def test_metric_result_rejects_out_of_range_score() -> None:
    with pytest.raises(ValueError, match="0.0 y 1.0"):
        MetricResult(
            case_id="case-1",
            score=1.1,
            passed=True,
            actual=True,
            expected=True,
        )


def test_measurement_contracts_serialize() -> None:
    case = BenchmarkCase(
        case_id="source-1",
        capability="source_validation",
        input_payload={"source_ref": "repo://triade"},
        expected=True,
    )
    suite = BenchmarkSuite(
        suite_id="source-validation",
        version="1.0.0",
        capability="source_validation",
        cases=(case,),
    )
    result = MetricResult(
        case_id=case.case_id,
        score=1.0,
        passed=True,
        actual=True,
        expected=True,
    )
    run = EvaluationRun(
        evaluation_id="eval-1",
        suite_id=suite.suite_id,
        suite_version=suite.version,
        subject_id="learning-pipeline",
        results=(result,),
        aggregate_score=1.0,
        created_at="2026-07-11T00:00:00Z",
    )
    baseline = CapabilityBaseline(
        baseline_id="baseline-1",
        capability=suite.capability,
        suite_id=suite.suite_id,
        suite_version=suite.version,
        subject_id=run.subject_id,
        aggregate_score=run.aggregate_score,
        evaluation_id=run.evaluation_id,
        created_at=run.created_at,
    )
    comparison = EvaluationComparison(
        baseline_evaluation_id="eval-0",
        candidate_evaluation_id=run.evaluation_id,
        baseline_score=0.8,
        candidate_score=1.0,
        absolute_delta=0.2,
        percent_delta=25.0,
        improved_cases=(case.case_id,),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )

    assert suite.to_dict()["cases"][0]["case_id"] == "source-1"
    assert run.to_dict()["aggregate_score"] == 1.0
    assert baseline.to_dict()["evaluation_id"] == "eval-1"
    assert comparison.to_dict()["decision"] == "improved"


def test_suite_rejects_mixed_capabilities() -> None:
    with pytest.raises(ValueError, match="capacidad"):
        BenchmarkSuite(
            suite_id="mixed",
            version="1.0.0",
            capability="identity_protection",
            cases=(
                BenchmarkCase(
                    case_id="case-1",
                    capability="source_validation",
                    input_payload={},
                    expected=True,
                ),
            ),
        )
