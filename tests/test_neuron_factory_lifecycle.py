import json
import sqlite3
from pathlib import Path

import pytest

from triade.capabilities import CapabilityRegistry, bootstrap_core_capabilities
from triade.neuron_factory import (
    NeuronLifecycleManager,
    NeuronSpecification,
    NeuronSpecificationStore,
    ResourceBudget,
)


def prepare_promoted_candidate(db_path: Path) -> str:
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
        evaluation_suites=("research-quality@1.0.0",),
        rollback_policy="research-neuron-rollback",
        critical=True,
        resource_budget=ResourceBudget(1024, 300, 64),
    )
    store.register(specification)
    for state in ("specified", "training", "evaluated", "promoted"):
        store.transition(specification.neuron_id, specification.version, state)

    candidate_id = "candidate-promoted"
    manifest = {
        "candidate_id": candidate_id,
        "neuron_id": specification.neuron_id,
        "version": specification.version,
        "sandbox_id": "sandbox-promoted",
        "specification_sha256": "a" * 64,
        "status": "promoted",
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS neuron_candidates (
                candidate_id TEXT PRIMARY KEY,
                neuron_id TEXT NOT NULL,
                version TEXT NOT NULL,
                sandbox_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS neuron_candidate_executions (
                execution_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                status TEXT NOT NULL,
                artifact_json TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        conn.execute(
            """INSERT INTO neuron_candidates
            (candidate_id, neuron_id, version, sandbox_id, status, manifest_json)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                candidate_id,
                specification.neuron_id,
                specification.version,
                manifest["sandbox_id"],
                "promoted",
                json.dumps(manifest, sort_keys=True),
            ),
        )
    return candidate_id


def test_promoted_neuron_registers_demonstrated_capability(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    candidate_id = prepare_promoted_candidate(db_path)

    registered = NeuronLifecycleManager(db_path).register_demonstrated_capabilities(candidate_id)

    assert [item["capability_id"] for item in registered] == ["research_verified"]
    capability = CapabilityRegistry(db_path).get("research_verified", "1.0.0")
    assert capability is not None
    assert capability["state"] == "active"
    assert capability["dependencies"] == ["identity_core"]
    assert capability["rollback_policy"] == "research-neuron-rollback"


def test_registration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    candidate_id = prepare_promoted_candidate(db_path)
    manager = NeuronLifecycleManager(db_path)

    assert manager.register_demonstrated_capabilities(candidate_id) == manager.register_demonstrated_capabilities(candidate_id)


def test_rollback_blocks_capability_and_quarantines_neuron(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    candidate_id = prepare_promoted_candidate(db_path)
    manager = NeuronLifecycleManager(db_path)
    manager.register_demonstrated_capabilities(candidate_id)

    result = manager.rollback(candidate_id, "regresión posterior")

    assert result["status"] == "rolled_back"
    assert result["specification"]["state"] == "quarantined"
    assert CapabilityRegistry(db_path).get("research_verified", "1.0.0")["state"] == "blocked"
    assert manager.candidates.get(candidate_id)["status"] == "rolled_back"
    with pytest.raises(ValueError, match="solo un candidato promovido"):
        manager.rollback(candidate_id, "segunda reversión")


def test_snapshot_reports_lifecycle_state(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    candidate_id = prepare_promoted_candidate(db_path)
    manager = NeuronLifecycleManager(db_path)

    before = manager.snapshot()
    manager.register_demonstrated_capabilities(candidate_id)
    manager.rollback(candidate_id, "prueba")
    after = manager.snapshot()

    assert before["candidates"] == {"promoted": 1}
    assert before["specifications"] == {"promoted": 1}
    assert before["executions"] == 0
    assert after["candidates"] == {"rolled_back": 1}
    assert after["specifications"] == {"quarantined": 1}
