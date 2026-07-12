from pathlib import Path

import pytest

from triade.neuron_factory import (
    NeuronSpecification,
    NeuronSpecificationStore,
    ResourceBudget,
)


def make_spec(*, critical: bool = False) -> NeuronSpecification:
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
        evaluation_suites=("research-quality@1.0.0",) if critical else (),
        rollback_policy="research-neuron-rollback" if critical else None,
        critical=critical,
        resource_budget=ResourceBudget(
            max_memory_mb=1024,
            max_runtime_seconds=300,
            max_storage_mb=512,
        ),
    )


def test_specification_requires_sandbox_and_budget() -> None:
    specification = make_spec()
    specification.validate()

    without_sandbox = NeuronSpecification(
        **{**specification.to_dict(), "sandbox_required": False, "resource_budget": specification.resource_budget}
    )
    with pytest.raises(ValueError, match="sandbox"):
        without_sandbox.validate()


def test_critical_neuron_requires_suite_and_rollback() -> None:
    specification = make_spec()
    invalid = NeuronSpecification(
        **{**specification.to_dict(), "critical": True, "resource_budget": specification.resource_budget}
    )

    with pytest.raises(ValueError, match="suite y rollback"):
        invalid.validate()


def test_store_registers_transitions_and_history(tmp_path: Path) -> None:
    store = NeuronSpecificationStore(tmp_path / "triade.db")
    specification = make_spec(critical=True)

    registered = store.register(specification)
    specified = store.transition(specification.neuron_id, specification.version, "specified")
    training = store.transition(specification.neuron_id, specification.version, "training")

    assert registered["state"] == "draft"
    assert specified["state"] == "specified"
    assert training["state"] == "training"
    assert [event["action"] for event in store.history(specification.neuron_id)] == [
        "registered",
        "state_changed",
        "state_changed",
    ]


def test_invalid_transition_is_rejected(tmp_path: Path) -> None:
    store = NeuronSpecificationStore(tmp_path / "triade.db")
    specification = make_spec()
    store.register(specification)

    with pytest.raises(ValueError, match="transición inválida"):
        store.transition(specification.neuron_id, specification.version, "promoted")


def test_export_is_deterministic_for_unchanged_store(tmp_path: Path) -> None:
    store = NeuronSpecificationStore(tmp_path / "triade.db")
    specification = make_spec(critical=True)
    store.register(specification)

    first = store.export(specification.neuron_id, specification.version)
    second = store.export(specification.neuron_id, specification.version)

    assert first == second
    assert len(first["sha256"]) == 64
    assert first["specification"]["resource_budget"]["max_memory_mb"] == 1024
