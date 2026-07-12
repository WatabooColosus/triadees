from pathlib import Path

import pytest

from triade.capabilities import bootstrap_core_capabilities
from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.neuron_factory import (
    NeuronCandidateFactory,
    NeuronEvaluationCoordinator,
    NeuronSpecification,
    NeuronSpecificationStore,
    ResourceBudget,
    SandboxExecutionEngine,
)
from triade.regression import MetricPolicy


def prepare_executed_candidate(db_path: Path) -> dict:
    bootstrap_core_capabilities(db_path)
    store = NeuronSpecificationStore(db_path)
    specification = NeuronSpecification(
        neuron_id="neuron.research",
        name="Research Neuron",
        mission="investigar fuentes verificables",
        domain="research",
        version="1.0.0",
        owner="central",
        component="triade.neurons.research",
        input_contract={"type": "object"},
        output_contract={"type": "object"},
        provides_capabilities=("research_verified",),
        requires_capabilities=("identity_core",),
        training_policy="configuration",
        resource_budget=ResourceBudget(1024, 300, 1),
    )
    store.register(specification)
    store.transition(specification.neuron_id, specification.version, "specified")
    factory = NeuronCandidateFactory(db_path)
    candidate = factory.create(specification.neuron_id, specification.version)
    SandboxExecutionEngine(db_path).execute_configuration(candidate["candidate_id"], {"mode": "safe"})
    persisted = factory.get(candidate["candidate_id"])
    assert persisted is not None
    return persisted


def evaluation(evaluation_id: str, subject_id: str, score: float) -> EvaluationRun:
    result = MetricResult(
        case_id="quality",
        score=score,
        passed=score >= 0.7,
        actual=score,
        expected=0.7,
    )
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id="research-quality",
        suite_version="1.0.0",
        subject_id=subject_id,
        results=(result,),
        aggregate_score=score,
        created_at="2026-07-12T00:00:00Z",
    )


def comparison(baseline: EvaluationRun, candidate: EvaluationRun, decision: str) -> EvaluationComparison:
    delta = candidate.aggregate_score - baseline.aggregate_score
    return EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=baseline.aggregate_score,
        candidate_score=candidate.aggregate_score,
        absolute_delta=delta,
        percent_delta=delta / baseline.aggregate_score,
        improved_cases=("quality",) if delta > 0 else (),
        degraded_cases=("quality",) if delta < 0 else (),
        critical_regressions=(),
        decision=decision,
    )


def test_improved_candidate_with_passing_regression_can_be_promoted(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    manifest = prepare_executed_candidate(db_path)
    baseline = evaluation("baseline-eval", manifest["candidate_id"], 0.70)
    candidate = evaluation("candidate-eval", manifest["candidate_id"], 0.90)
    coordinator = NeuronEvaluationCoordinator(db_path)

    result = coordinator.record_evidence(
        manifest["candidate_id"],
        hypothesis="la configuración mejora calidad",
        capability="research_verified",
        baseline=baseline,
        candidate=candidate,
        comparison=comparison(baseline, candidate, "improved"),
        policies=(MetricPolicy("quality", severity="high"),),
        artifact_ref=manifest["execution_id"],
    )
    promoted = coordinator.promote(manifest["candidate_id"])

    assert result["promotable"] is True
    assert promoted["status"] == "promoted"
    assert NeuronSpecificationStore(db_path).get("neuron.research", "1.0.0")["state"] == "promoted"
    assert NeuronCandidateFactory(db_path).get(manifest["candidate_id"])["status"] == "promoted"


def test_neutral_candidate_cannot_be_promoted(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    manifest = prepare_executed_candidate(db_path)
    baseline = evaluation("baseline-eval", manifest["candidate_id"], 0.80)
    candidate = evaluation("candidate-eval", manifest["candidate_id"], 0.80)
    coordinator = NeuronEvaluationCoordinator(db_path)
    coordinator.record_evidence(
        manifest["candidate_id"],
        hypothesis="la configuración mejora calidad",
        capability="research_verified",
        baseline=baseline,
        candidate=candidate,
        comparison=comparison(baseline, candidate, "neutral"),
        policies=(MetricPolicy("quality", severity="high"),),
        artifact_ref=manifest["execution_id"],
    )

    with pytest.raises(ValueError, match="no demuestra mejora"):
        coordinator.promote(manifest["candidate_id"])


def test_forged_improvement_decision_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    manifest = prepare_executed_candidate(db_path)
    baseline = evaluation("baseline-eval", manifest["candidate_id"], 0.90)
    candidate = evaluation("candidate-eval", manifest["candidate_id"], 0.70)

    with pytest.raises(ValueError, match="decisión de comparación inconsistente"):
        NeuronEvaluationCoordinator(db_path).record_evidence(
            manifest["candidate_id"],
            hypothesis="la configuración mejora calidad",
            capability="research_verified",
            baseline=baseline,
            candidate=candidate,
            comparison=comparison(baseline, candidate, "improved"),
            policies=(MetricPolicy("quality", severity="high"),),
            artifact_ref=manifest["execution_id"],
        )


def test_regression_failure_blocks_promotion_and_allows_quarantine(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    manifest = prepare_executed_candidate(db_path)
    subject = manifest["candidate_id"]
    baseline = EvaluationRun(
        evaluation_id="baseline-eval",
        suite_id="research-quality",
        suite_version="1.0.0",
        subject_id=subject,
        results=(
            MetricResult("quality", 0.90, True, 0.90, 0.70),
            MetricResult("throughput", 0.20, False, 0.20, 0.70),
        ),
        aggregate_score=0.55,
        created_at="2026-07-12T00:00:00Z",
    )
    candidate = EvaluationRun(
        evaluation_id="candidate-eval",
        suite_id="research-quality",
        suite_version="1.0.0",
        subject_id=subject,
        results=(
            MetricResult("quality", 0.70, True, 0.70, 0.70),
            MetricResult("throughput", 1.00, True, 1.00, 0.70),
        ),
        aggregate_score=0.85,
        created_at="2026-07-12T00:00:01Z",
    )
    measured = EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=0.55,
        candidate_score=0.85,
        absolute_delta=0.30,
        percent_delta=0.30 / 0.55,
        improved_cases=("throughput",),
        degraded_cases=("quality",),
        critical_regressions=(),
        decision="improved",
    )
    coordinator = NeuronEvaluationCoordinator(db_path)
    result = coordinator.record_evidence(
        manifest["candidate_id"],
        hypothesis="la configuración mejora rendimiento global",
        capability="research_verified",
        baseline=baseline,
        candidate=candidate,
        comparison=measured,
        policies=(MetricPolicy("quality", severity="high", max_absolute_drop=0.0),),
        artifact_ref=manifest["execution_id"],
    )

    assert result["regression_decision"] == "fail"
    with pytest.raises(ValueError, match="Regression Gate"):
        coordinator.promote(manifest["candidate_id"])
    quarantined = coordinator.quarantine(manifest["candidate_id"], "regresión detectada")
    assert quarantined["status"] == "quarantined"
