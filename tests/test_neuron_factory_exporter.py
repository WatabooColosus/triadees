import json
import sqlite3
from pathlib import Path

from triade.capabilities import bootstrap_core_capabilities
from triade.neuron_factory import (
    NeuronLifecycleExporter,
    NeuronSpecification,
    NeuronSpecificationStore,
    ResourceBudget,
)


def test_lifecycle_export_is_deterministic(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bootstrap_core_capabilities(db_path)
    store = NeuronSpecificationStore(db_path)
    specification = NeuronSpecification(
        neuron_id="neuron.audit",
        name="Audit Neuron",
        mission="producir evidencia auditable",
        domain="audit",
        version="1.0.0",
        owner="central",
        component="triade.neurons.audit",
        input_contract={"type": "object"},
        output_contract={"type": "object"},
        provides_capabilities=("audit_verified",),
        requires_capabilities=("identity_core",),
        resource_budget=ResourceBudget(256, 60, 16),
    )
    store.register(specification)
    candidate = {
        "candidate_id": "candidate-audit",
        "neuron_id": specification.neuron_id,
        "version": specification.version,
        "sandbox_id": "sandbox-audit",
        "specification_sha256": "a" * 64,
        "status": "created",
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
                candidate["candidate_id"], candidate["neuron_id"], candidate["version"],
                candidate["sandbox_id"], candidate["status"], json.dumps(candidate, sort_keys=True),
            ),
        )

    exporter = NeuronLifecycleExporter(db_path)
    first = exporter.export(candidate["candidate_id"])
    second = exporter.export(candidate["candidate_id"])

    assert first == second
    assert len(first["sha256"]) == 64
    assert first["candidate"]["candidate_id"] == "candidate-audit"
    assert first["specification"]["neuron_id"] == "neuron.audit"
