from pathlib import Path

import pytest

from triade.capabilities import bootstrap_core_capabilities
from triade.neuron_factory import (
    NeuronCandidateFactory,
    NeuronSpecification,
    NeuronSpecificationStore,
    ResourceBudget,
    SandboxExecutionEngine,
)


def prepare_candidate(
    db_path: Path, policy: str = "configuration"
) -> tuple[NeuronSpecificationStore, dict]:
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
        training_policy=policy,
        resource_budget=ResourceBudget(
            max_memory_mb=1024,
            max_runtime_seconds=300,
            max_storage_mb=1,
        ),
    )
    store.register(specification)
    store.transition(specification.neuron_id, specification.version, "specified")
    candidate = NeuronCandidateFactory(db_path).create(
        specification.neuron_id, specification.version
    )
    return store, candidate


def test_configuration_execution_creates_auditable_artifact(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    store, candidate = prepare_candidate(db_path)
    engine = SandboxExecutionEngine(db_path)

    artifact = engine.execute_configuration(
        candidate["candidate_id"],
        {"model": "qwen2.5:3b", "temperature": 0.1},
    )

    assert artifact["status"] == "completed"
    assert artifact["sandbox_id"] == candidate["sandbox_id"]
    assert len(artifact["sha256"]) == 64
    assert engine.get_execution(artifact["execution_id"]) == artifact
    assert engine.list_for_candidate(candidate["candidate_id"]) == [artifact]
    assert store.get("neuron.research", "1.0.0")["state"] == "evaluated"
    assert (
        NeuronCandidateFactory(db_path).get(candidate["candidate_id"])["status"]
        == "executed"
    )


def test_execution_rejects_empty_configuration(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _, candidate = prepare_candidate(db_path)

    with pytest.raises(ValueError, match="objeto no vacío"):
        SandboxExecutionEngine(db_path).execute_configuration(
            candidate["candidate_id"], {}
        )


def test_candidate_cannot_execute_twice(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _, candidate = prepare_candidate(db_path)
    engine = SandboxExecutionEngine(db_path)
    engine.execute_configuration(candidate["candidate_id"], {"mode": "safe"})

    with pytest.raises(ValueError, match="no está disponible"):
        engine.execute_configuration(candidate["candidate_id"], {"mode": "safe"})


def test_storage_budget_is_enforced(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    _, candidate = prepare_candidate(db_path)
    oversized = {"payload": "x" * (1024 * 1024 + 1)}

    with pytest.raises(ValueError, match="presupuesto de almacenamiento"):
        SandboxExecutionEngine(db_path).execute_configuration(
            candidate["candidate_id"], oversized
        )


def test_code_execution_requires_explicit_specification(tmp_path):
    db = tmp_path / "triade.db"
    _, candidate = prepare_candidate(db)
    with pytest.raises(ValueError, match="python_code"):
        SandboxExecutionEngine(db).execute_code(candidate["candidate_id"], "pass")


def test_code_failure_does_not_advance_candidate(tmp_path, monkeypatch):
    from triade.sandbox.code_execution import DockerCodeSandbox

    db = tmp_path / "triade.db"
    store, candidate = prepare_candidate(db, policy="python_code")

    def fail(*args, **kwargs):
        raise RuntimeError("sandbox unavailable")

    monkeypatch.setattr(DockerCodeSandbox, "execute", fail)
    engine = SandboxExecutionEngine(db)
    with pytest.raises(RuntimeError, match="unavailable"):
        engine.execute_code(candidate["candidate_id"], "pass")
    assert engine.list_for_candidate(candidate["candidate_id"]) == []
    assert engine.candidates.get(candidate["candidate_id"])["status"] == "created"
    assert store.get("neuron.research", "1.0.0")["state"] == "training"


def test_code_receipt_is_persisted_without_quality_claim(tmp_path, monkeypatch):
    from triade.sandbox.code_execution import DockerCodeSandbox

    db = tmp_path / "triade.db"
    _, candidate = prepare_candidate(db, policy="python_code")
    monkeypatch.setattr(
        DockerCodeSandbox,
        "execute",
        lambda *a, **k: {"exit_code": 0, "quality_verified": False},
    )
    engine = SandboxExecutionEngine(db)
    artifact = engine.execute_code(candidate["candidate_id"], "print('ok')")
    assert artifact["code_execution"]["quality_verified"] is False
    assert engine.get_execution(artifact["execution_id"]) == artifact
    assert engine.candidates.get(candidate["candidate_id"])["status"] == "executed"
