from pathlib import Path

import pytest

from triade.capabilities import bootstrap_core_capabilities
from triade.neuron_factory import (
    NeuronCandidateFactory,
    NeuronSpecification,
    NeuronSpecificationStore,
    ResourceBudget,
)


def make_spec() -> NeuronSpecification:
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
        requires_capabilities=("identity_core",),
        training_policy="configuration",
        resource_budget=ResourceBudget(
            max_memory_mb=1024,
            max_runtime_seconds=300,
            max_storage_mb=512,
        ),
    )


def prepare_specification(db_path: Path) -> NeuronSpecificationStore:
    bootstrap_core_capabilities(db_path)
    store = NeuronSpecificationStore(db_path)
    specification = make_spec()
    store.register(specification)
    store.transition(specification.neuron_id, specification.version, "specified")
    return store


def test_candidate_requires_specified_state(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bootstrap_core_capabilities(db_path)
    specification = make_spec()
    NeuronSpecificationStore(db_path).register(specification)

    with pytest.raises(ValueError, match="estado specified"):
        NeuronCandidateFactory(db_path).create(specification.neuron_id, specification.version)


def test_candidate_validates_required_capabilities(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    store = NeuronSpecificationStore(db_path)
    specification = make_spec()
    store.register(specification)
    store.transition(specification.neuron_id, specification.version, "specified")

    with pytest.raises(ValueError, match="capacidades requeridas inexistentes"):
        NeuronCandidateFactory(db_path).create(specification.neuron_id, specification.version)


def test_candidate_is_created_in_unique_sandbox(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    store = prepare_specification(db_path)
    factory = NeuronCandidateFactory(db_path)

    manifest = factory.create("neuron.research", "1.0.0")

    assert manifest["status"] == "created"
    assert manifest["sandbox_id"].startswith("sandbox-")
    assert manifest["required_capabilities"] == ["identity_core"]
    assert manifest["provided_capabilities"] == ["research_verified"]
    assert len(manifest["sha256"]) == 64
    assert factory.get(manifest["candidate_id"]) == manifest
    assert store.get("neuron.research", "1.0.0")["state"] == "training"


def test_candidate_manifest_preserves_resource_limits(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    prepare_specification(db_path)

    manifest = NeuronCandidateFactory(db_path).create("neuron.research", "1.0.0")

    assert manifest["resource_budget"] == {
        "max_memory_mb": 1024,
        "max_runtime_seconds": 300,
        "max_storage_mb": 512,
    }
