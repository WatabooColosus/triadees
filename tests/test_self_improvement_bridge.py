from pathlib import Path

import pytest

from triade.neuron_factory import NeuronSpecification, NeuronSpecificationStore, ResourceBudget
from triade.self_improvement.bridge import ImprovementBudget, ImprovementNeuronFactoryBridge
from triade.self_improvement.contracts import ImprovementProposal, ImprovementSignal
from triade.self_improvement.store import ImprovementStore


def prepare(
    db_path: Path,
    *,
    max_candidates: int = 1,
    resource_budget: ResourceBudget | None = None,
) -> tuple[ImprovementNeuronFactoryBridge, str]:
    store = ImprovementStore(db_path)
    store.register_signal(
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
    store.create_proposal(
        ImprovementProposal(
            proposal_id="proposal-quality",
            signal_id="signal-quality",
            hypothesis="una nueva neurona mejora la calidad",
            requested_capability="research_verified",
            requires_human_approval=True,
            max_candidates=max_candidates,
        )
    )
    specifications = NeuronSpecificationStore(db_path)
    specification = NeuronSpecification(
        neuron_id="neuron.research.candidate",
        name="Research Candidate",
        mission="mejorar la calidad de investigación",
        domain="research",
        version="1.0.0",
        owner="central",
        component="triade.neurons.research_candidate",
        input_contract={"type": "object"},
        output_contract={"type": "object"},
        provides_capabilities=("research_verified",),
        resource_budget=resource_budget or ResourceBudget(512, 120, 32),
    )
    specifications.register(specification)
    specifications.transition(specification.neuron_id, specification.version, "specified")
    bridge = ImprovementNeuronFactoryBridge(db_path)
    return bridge, specification.neuron_id


def test_proposal_requires_explicit_approval(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bridge, neuron_id = prepare(db_path)

    with pytest.raises(ValueError, match="aprobada"):
        bridge.create_candidate("proposal-quality", neuron_id=neuron_id, version="1.0.0")

    approved = bridge.approve("proposal-quality", approved_by="human-operator")
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "human-operator"


def test_approved_proposal_creates_sandbox_candidate(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bridge, neuron_id = prepare(db_path)
    bridge.approve("proposal-quality", approved_by="human-operator")

    result = bridge.create_candidate(
        "proposal-quality", neuron_id=neuron_id, version="1.0.0"
    )

    assert result["candidate"]["status"] == "created"
    assert result["candidate"]["sandbox_id"].startswith("sandbox-")
    assert result["resource_usage"] == {
        "active_candidates": 1,
        "memory_mb": 512,
        "runtime_seconds": 120,
        "storage_mb": 32,
    }


def test_requested_capability_must_match_specification(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bridge, _ = prepare(db_path)
    specifications = NeuronSpecificationStore(db_path)
    other = NeuronSpecification(
        neuron_id="neuron.other",
        name="Other",
        mission="otra capacidad",
        domain="other",
        version="1.0.0",
        owner="central",
        component="triade.neurons.other",
        input_contract={"type": "object"},
        output_contract={"type": "object"},
        provides_capabilities=("other_capability",),
        resource_budget=ResourceBudget(128, 30, 8),
    )
    specifications.register(other)
    specifications.transition(other.neuron_id, other.version, "specified")
    bridge.approve("proposal-quality", approved_by="human-operator")

    with pytest.raises(ValueError, match="no aporta"):
        bridge.create_candidate("proposal-quality", neuron_id=other.neuron_id, version="1.0.0")


def test_global_budget_blocks_candidate_before_factory_execution(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _, neuron_id = prepare(db_path, resource_budget=ResourceBudget(1024, 120, 32))
    bridge = ImprovementNeuronFactoryBridge(
        db_path,
        budget=ImprovementBudget(
            max_active_candidates=1,
            max_memory_mb=512,
            max_runtime_seconds=300,
            max_storage_mb=64,
        ),
    )
    bridge.approve("proposal-quality", approved_by="human-operator")

    with pytest.raises(ValueError, match="memory_mb"):
        bridge.create_candidate("proposal-quality", neuron_id=neuron_id, version="1.0.0")

    assert NeuronSpecificationStore(db_path).get(neuron_id, "1.0.0")["state"] == "specified"


def test_release_frees_global_resources(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bridge, neuron_id = prepare(db_path)
    bridge.approve("proposal-quality", approved_by="human-operator")
    created = bridge.create_candidate(
        "proposal-quality", neuron_id=neuron_id, version="1.0.0"
    )

    released = bridge.release_candidate(created["candidate"]["candidate_id"], outcome="completed")

    assert released["proposal_status"] == "completed"
    assert bridge.resource_usage() == {
        "active_candidates": 0,
        "memory_mb": 0,
        "runtime_seconds": 0,
        "storage_mb": 0,
    }
