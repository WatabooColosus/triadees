from __future__ import annotations

import pytest

from triade.evaluation import EvaluationRun, MetricResult
from triade.regression.critical_suites import (
    CriticalMetricDefinition,
    CriticalSuiteDefinition,
    CriticalSuiteRegistry,
)


def make_run(suite_id: str, version: str, metric_ids: tuple[str, ...]) -> EvaluationRun:
    return EvaluationRun(
        evaluation_id="eval-1",
        suite_id=suite_id,
        suite_version=version,
        subject_id="subject-1",
        results=tuple(
            MetricResult(case_id=metric_id, score=1.0, passed=True, actual=1.0, expected=1.0)
            for metric_id in metric_ids
        ),
        aggregate_score=1.0,
        created_at="2026-07-11T00:00:00+00:00",
    )


def test_default_registry_contains_three_versioned_critical_suites() -> None:
    registry = CriticalSuiteRegistry()

    suites = registry.list()

    assert {item["suite_id"] for item in suites} == {
        "triade-core-safety",
        "learning-promotion",
        "semantic-memory-governance",
    }
    assert all(item["version"] == "1.0.0" for item in suites)
    assert all(item["immutable"] is True for item in suites)


def test_suite_validates_matching_run_and_builds_policies() -> None:
    suite = CriticalSuiteRegistry().get("triade-core-safety", "1.0.0")
    run = make_run("triade-core-safety", "1.0.0", ("identity_core", "safety", "isolation"))

    suite.validate_run(run)
    policies = suite.policies()

    assert len(policies) == 3
    assert all(policy.severity == "critical" for policy in policies)


def test_suite_rejects_wrong_version() -> None:
    suite = CriticalSuiteRegistry().get("learning-promotion", "1.0.0")
    run = make_run(
        "learning-promotion",
        "2.0.0",
        ("identity_core", "safety", "evidence_quality", "generalization", "outcome_quality"),
    )

    with pytest.raises(ValueError, match="suite_version incompatible"):
        suite.validate_run(run)


def test_suite_rejects_missing_required_metric() -> None:
    suite = CriticalSuiteRegistry().get("semantic-memory-governance", "1.0.0")
    run = make_run(
        "semantic-memory-governance",
        "1.0.0",
        ("identity_core", "authorized_influence", "source_traceability"),
    )

    with pytest.raises(ValueError, match="quarantine_enforcement"):
        suite.validate_run(run)


def test_registry_rejects_duplicate_suite_version() -> None:
    suite = CriticalSuiteDefinition(
        suite_id="duplicate",
        version="1.0.0",
        capability="test",
        metrics=(CriticalMetricDefinition("metric", "critical"),),
    )
    registry = CriticalSuiteRegistry(suites=(suite,))

    with pytest.raises(ValueError, match="duplicada"):
        registry.register(suite)
