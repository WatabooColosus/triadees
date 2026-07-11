from __future__ import annotations

import json
from pathlib import Path

import pytest

from triade.evaluation import EvaluationRun, MetricResult
from triade.regression import MetricPolicy, RegressionGate
from triade.regression.artifacts import RegressionArtifactExporter
from triade.regression.protection_registry import (
    CapabilityProtectionRegistry,
    ProtectionRule,
)


def make_run(evaluation_id: str, scores: dict[str, float]) -> EvaluationRun:
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
        subject_id="subject-v1",
        results=results,
        aggregate_score=sum(scores.values()) / len(scores),
        created_at="2026-07-11T00:00:00+00:00",
    )


def test_registry_installs_immutable_core_defaults(tmp_path: Path) -> None:
    registry = CapabilityProtectionRegistry(tmp_path / "triade.db")

    installed = registry.install_core_defaults()
    rules = registry.list_for_capability("learning")

    assert len(installed) == 3
    assert {rule.metric_id for rule in rules} == {
        "identity_core",
        "safety",
        "isolation",
    }
    assert all(rule.immutable for rule in rules)
    assert all(rule.severity == "critical" for rule in rules)


def test_immutable_rule_cannot_be_disabled_or_changed(tmp_path: Path) -> None:
    registry = CapabilityProtectionRegistry(tmp_path / "triade.db")
    rule = ProtectionRule(
        capability="learning",
        metric_id="identity_core",
        version="1.0.0",
        severity="critical",
        immutable=True,
    )
    registry.register(rule)

    with pytest.raises(ValueError, match="inmutable"):
        registry.disable(rule.rule_id)

    changed = ProtectionRule(
        capability="learning",
        metric_id="identity_core",
        version="1.0.0",
        severity="high",
        immutable=True,
    )
    with pytest.raises(ValueError, match="inmutable"):
        registry.register(changed)


def test_registry_builds_metric_policies(tmp_path: Path) -> None:
    registry = CapabilityProtectionRegistry(tmp_path / "triade.db")
    registry.register(
        ProtectionRule(
            capability="memory",
            metric_id="retrieval_accuracy",
            version="1.0.0",
            severity="high",
            max_absolute_drop=0.02,
            max_relative_drop=0.03,
            human_override_allowed=True,
        )
    )

    policies = registry.policies_for("memory")

    assert policies == (
        MetricPolicy(
            metric_id="retrieval_accuracy",
            severity="high",
            max_absolute_drop=0.02,
            max_relative_drop=0.03,
            required=True,
        ),
    )


def test_immutable_rule_rejects_human_override() -> None:
    with pytest.raises(ValueError, match="override"):
        ProtectionRule(
            capability="learning",
            metric_id="safety",
            version="1.0.0",
            severity="critical",
            immutable=True,
            human_override_allowed=True,
        )


def test_exporter_writes_complete_hashed_artifact(tmp_path: Path) -> None:
    baseline = make_run(
        "baseline",
        {"identity_core": 1.0, "safety": 1.0, "isolation": 1.0},
    )
    candidate = make_run(
        "candidate",
        {"identity_core": 1.0, "safety": 1.0, "isolation": 1.0},
    )
    policies = (
        MetricPolicy("identity_core", severity="critical"),
        MetricPolicy("safety", severity="critical"),
        MetricPolicy("isolation", severity="critical"),
    )
    gate = RegressionGate(tmp_path / "triade.db")
    report = gate.evaluate(
        report_id="report-001",
        candidate_id="candidate-001",
        capability="learning",
        baseline=baseline,
        candidate=candidate,
        policies=policies,
    )
    exporter = RegressionArtifactExporter(tmp_path / "artifacts")

    artifact = exporter.export(
        report=report,
        policies=policies,
        baseline=baseline,
        candidate=candidate,
        metadata={"run_ref": "test-run"},
    )

    directory = Path(artifact["directory"])
    assert artifact["decision"] == "pass"
    assert len(artifact["manifest_sha256"]) == 64
    for filename in (
        "report.json",
        "policies.json",
        "baseline.json",
        "candidate.json",
        "metadata.json",
        "manifest.json",
    ):
        assert (directory / filename).exists()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {
        "report.json",
        "policies.json",
        "baseline.json",
        "candidate.json",
        "metadata.json",
    }


def test_exporter_rejects_mismatched_evidence(tmp_path: Path) -> None:
    baseline = make_run("baseline", {"identity_core": 1.0})
    candidate = make_run("candidate", {"identity_core": 1.0})
    gate = RegressionGate(tmp_path / "triade.db")
    report = gate.evaluate(
        report_id="report-002",
        candidate_id="candidate-002",
        capability="learning",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity_core", severity="critical"),),
    )
    wrong_baseline = make_run("wrong-baseline", {"identity_core": 1.0})

    with pytest.raises(ValueError, match="baseline"):
        RegressionArtifactExporter(tmp_path / "artifacts").export(
            report=report,
            policies=(MetricPolicy("identity_core", severity="critical"),),
            baseline=wrong_baseline,
            candidate=candidate,
        )
