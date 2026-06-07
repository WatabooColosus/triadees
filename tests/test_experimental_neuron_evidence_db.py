from __future__ import annotations

import json
from pathlib import Path

from triade.core.experimental_neuron_evidence import build_experimental_evidence_ledger
from triade.core.neuron_activity_store import NeuronActivityStore
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry


def seed_run(db_path: Path, run_id: str) -> None:
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO runs (run_id, user_input, status)
            VALUES (?, ?, ?)
            """,
            (run_id, "test input", "ok"),
        )


def test_evidence_ledger_reads_db_first(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"

    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name="neurona-db-ledger",
        mission="Probar ledger DB.",
        domain="system_governance",
        rules=["Solo diagnóstico"],
        status="experimental",
        created_by="test",
    ))
    neuron = registry.get_neuron("neurona-db-ledger")
    assert neuron is not None

    seed_run(db_path, "run-db-001")

    activity = {
        "active": True,
        "count": 1,
        "activations": [
            {
                "neuron_id": neuron["id"],
                "name": "neurona-db-ledger",
                "status": "experimental",
                "domain": "system_governance",
                "active": True,
                "output": {
                    "diagnosis": ["d1", "d2"],
                    "test_plan": ["t1"],
                },
                "policy": "experimental_neuron_no_external_actions_no_stable_memory_write",
            }
        ],
    }

    NeuronActivityStore(db_path=db_path).record_run_activity("run-db-001", activity)

    ledger = build_experimental_evidence_ledger(
        runs_dir=runs_dir,
        db_path=db_path,
        limit=20,
        prefer_db=True,
    )

    assert ledger["summary"]["source"] == "db"
    assert ledger["summary"]["experimental_neurons_with_evidence"] == 1
    assert ledger["summary"]["total_activations"] == 1

    neuron_row = ledger["neurons"][0]
    assert neuron_row["name"] == "neurona-db-ledger"
    assert neuron_row["activation_count"] == 1
    assert neuron_row["diagnosis_count"] == 2
    assert neuron_row["test_plan_count"] == 1


def test_evidence_ledger_falls_back_to_artifacts(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    runs_dir = tmp_path / "runs"
    run_path = runs_dir / "run-artifact-001"
    run_path.mkdir(parents=True)

    activity = {
        "active": True,
        "count": 1,
        "activations": [
            {
                "neuron_id": 99,
                "name": "neurona-artifact-ledger",
                "status": "experimental",
                "domain": "system_governance",
                "active": True,
                "match": {"active": True, "reasons": ["artifact"]},
                "output": {
                    "diagnosis": ["d1"],
                    "test_plan": ["t1", "t2"],
                },
                "policy": "experimental_neuron_no_external_actions_no_stable_memory_write",
            }
        ],
    }

    (run_path / "experimental_neuron_activity.json").write_text(
        json.dumps(activity, ensure_ascii=False),
        encoding="utf-8",
    )

    ledger = build_experimental_evidence_ledger(
        runs_dir=runs_dir,
        db_path=db_path,
        limit=20,
        prefer_db=True,
    )

    assert ledger["summary"]["source"] == "artifacts"
    assert ledger["summary"]["experimental_neurons_with_evidence"] == 1
    assert ledger["neurons"][0]["name"] == "neurona-artifact-ledger"
    assert ledger["neurons"][0]["diagnosis_count"] == 1
    assert ledger["neurons"][0]["test_plan_count"] == 2
