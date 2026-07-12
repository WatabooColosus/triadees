from pathlib import Path

from triade.evaluation import EvaluationRun, MetricResult
from triade.neuron_factory import NeuronSpecification, NeuronSpecificationStore, ResourceBudget
from triade.regression import MetricPolicy
from triade.self_improvement.bridge import ImprovementNeuronFactoryBridge
from triade.self_improvement.contracts import ImprovementProposal, ImprovementSignal
from triade.self_improvement.orchestrator import SelfImprovementOrchestrator
from triade.self_improvement.store import ImprovementStore


def prepare(db_path: Path) -> None:
    improvements = ImprovementStore(db_path)
    improvements.register_signal(
        ImprovementSignal(
            signal_id="signal-quality",
            capability_id="research_verified",
            metric_id="quality",
            observed_score=0.5,
            target_score=0.8,
            impact=0.9,
            confidence=0.9,
            estimated_cost=1.0,
        )
    )
    improvements.create_proposal(
        ImprovementProposal(
            proposal_id="proposal-quality",
            signal_id="signal-quality",
            hypothesis="la configuración mejora la calidad",
            requested_capability="research_verified",
            requires_human_approval=True,
        )
    )
    ImprovementNeuronFactoryBridge(db_path).approve(
        "proposal-quality", approved_by="human-operator"
    )

    specifications = NeuronSpecificationStore(db_path)
    specification = NeuronSpecification(
        neuron_id="neuron.research.improved",
        name="Research Improved",
        mission="mejorar investigación verificable",
        domain="research",
        version="1.0.0",
        owner="central",
        component="triade.neurons.research_improved",
        input_contract={"type": "object"},
        output_contract={"type": "object"},
        provides_capabilities=("research_verified",),
        evaluation_suites=("quality-suite@1.0.0",),
        rollback_policy="automatic-canary",
        resource_budget=ResourceBudget(256, 60, 16),
    )
    specifications.register(specification)
    specifications.transition(specification.neuron_id, specification.version, "specified")


def run(candidate_id: str, score: float, evaluation_id: str) -> EvaluationRun:
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id="quality-suite",
        suite_version="1.0.0",
        subject_id=candidate_id,
        results=(
            MetricResult(
                case_id="quality",
                score=score,
                passed=score >= 0.8,
                actual=score,
                expected=1.0,
            ),
        ),
        aggregate_score=score,
        created_at="2026-07-12T00:00:00Z",
    )


def test_complete_cycle_reaches_canary(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    prepare(db_path)
    orchestrator = SelfImprovementOrchestrator(db_path)

    def evaluator(candidate_id: str, artifact: dict):
        assert artifact["status"] == "completed"
        return (
            run(candidate_id, 0.5, "eval-baseline"),
            run(candidate_id, 0.9, "eval-candidate"),
            (MetricPolicy("quality", severity="high"),),
        )

    result = orchestrator.run_once(
        "proposal-quality",
        neuron_id="neuron.research.improved",
        version="1.0.0",
        configuration={"mode": "verified"},
        evaluation_provider=evaluator,
        canary_min_observations=2,
        canary_max_observations=3,
    )

    assert result["status"] == "canary_running"
    assert result["promotion"]["status"] == "promoted"
    assert result["canary"]["traffic_percent"] == 10
    assert len(result["sha256"]) == 64
    snapshot = orchestrator.snapshot()
    assert snapshot["proposals"] == {"completed": 1}
    assert snapshot["candidate_links"] == {"completed": 1}
    assert snapshot["canaries"] == {"running": 1}
    assert snapshot["resource_usage"]["active_candidates"] == 0
    exported = orchestrator.export("proposal-quality")
    assert len(exported["sha256"]) == 64
    assert exported["canaries"][0]["status"] == "running"


def test_regression_is_quarantined_without_canary(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    prepare(db_path)
    orchestrator = SelfImprovementOrchestrator(db_path)

    def evaluator(candidate_id: str, artifact: dict):
        return (
            run(candidate_id, 0.8, "eval-baseline"),
            run(candidate_id, 0.6, "eval-candidate"),
            (MetricPolicy("quality", severity="high"),),
        )

    result = orchestrator.run_once(
        "proposal-quality",
        neuron_id="neuron.research.improved",
        version="1.0.0",
        configuration={"mode": "degraded"},
        evaluation_provider=evaluator,
    )

    assert result["status"] == "quarantined"
    assert result["evidence"]["promotable"] is False
    assert orchestrator.snapshot()["canaries"] == {}
    assert orchestrator.snapshot()["proposals"] == {"rejected": 1}
