from pathlib import Path

import pytest

from triade.capabilities import bootstrap_core_capabilities
from triade.neuron_factory import (
    NeuronCandidateFactory,
    NeuronSpecification,
    NeuronSpecificationStore,
    NeuronSpecificationValidator,
    ResourceBudget,
)


def make_spec(*, required: tuple[str, ...] = ("identity_core",)) -> NeuronSpecification:
    return NeuronSpecification(
        neuron_id="neuron.research",
        name="Research Neuron",
        mission="investigar fuentes verificables",
        domain="research",
        version="1.0.0",
        owner="central",
        component="triade.neurons.research",
        input_contract={"type": "object", "required": ["query"]},
        output_contract={"type": "object", "required": ["evidence"]},
        provides_capabilities=("research_verified",),
        requires_capabilities=required,
        resource_budget=ResourceBudget(
            max_memory_mb=1024,
            max_runtime_seconds=300,
            max_storage_mb=512,
        ),
    )


def test_validator_rejects_missing_required_capability(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    result = NeuronSpecificationValidator(db_path).validate(
        make_spec(required=("missing.capability",))
    )

    assert result.valid is False
    assert result.missing_capabilities == ("missing.capability",)
    with pytest.raises(ValueError, match="faltantes"):
        result.require_valid()


def test_candidate_requires_specified_state(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bootstrap_core_capabilities(db_path)
    store = NeuronSpecificationStore(db_path)
    specification = make_spec()
    store.register(specification)

    with pytest.raises(ValueError, match="estado specified"):
        NeuronCandidateFactory(db_path).create(specification.neuron_id, specification.version)


def test_candidate_is_created_in_auditable_sandbox(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bootstrap_core_capabilities(db_path)
    store = NeuronSpecificationStore(db_path)
    specification = make_spec()
    store.register(specification)
    store.transition(specification.neuron_id, specification.version, "specified")

    factory = NeuronCandidateFactory(db_path)
    candidate = factory.create(specification.neuron_id, specification.version)

    assert candidate["sandbox_ref"].startswith("sandbox://neurons/neuron.research/1.0.0/")
    assert len(candidate["specification_sha256"]) == 64
    assert factory.get(candidate["candidate_id"]) == candidate
    assert store.get(specification.neuron_id, specification.version)["state"] == "training"


def test_candidate_creation_rejects_blocked_dependency(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bootstrap_core_capabilities(db_path)
    from triade.capabilities import CapabilityRegistry

    registry = CapabilityRegistry(db_path)
    registry.set_state("identity_core", "1.0.0", "blocked")
    store = NeuronSpecificationStore(db_path)
    specification = make_spec()
    store.register(specification)
    store.transition(specification.neuron_id, specification.version, "specified")

    with pytest.raises(ValueError, match="bloqueadas"):
        NeuronCandidateFactory(db_path).create(specification.neuron_id, specification.version)
