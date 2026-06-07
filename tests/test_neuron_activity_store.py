from __future__ import annotations

from pathlib import Path

from triade.core.neuron_activity_store import NeuronActivityStore
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry


def test_neuron_activity_store_persists_experimental_activations(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"

    registry = NeuronRegistry(db_path=db_path)
    registry.register(NeuronSpec(
        name="neurona-test-activity",
        mission="Probar persistencia de actividad.",
        domain="system_governance",
        rules=["Solo diagnóstico"],
        status="experimental",
        created_by="test",
    ))

    neuron = registry.get_neuron("neurona-test-activity")
    assert neuron is not None

    activity = {
        "active": True,
        "count": 1,
        "activations": [
            {
                "neuron_id": neuron["id"],
                "name": "neurona-test-activity",
                "status": "experimental",
                "domain": "system_governance",
                "active": True,
                "match": {"active": True, "reasons": ["test"]},
                "output": {
                    "diagnosis": ["d1", "d2"],
                    "test_plan": ["t1"],
                },
                "policy": "experimental_neuron_no_external_actions_no_stable_memory_write",
            }
        ],
    }

    store = NeuronActivityStore(db_path=db_path)
    ids = store.store_activity(run_id="run-test-activity", activity=activity)

    assert len(ids) == 1

    rows = store.list_activity(name="neurona-test-activity")
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "run-test-activity"
    assert row["name"] == "neurona-test-activity"
    assert row["activated"] is True
    assert row["diagnosis_count"] == 2
    assert row["test_plan_count"] == 1
    assert row["activity_json"]["match"]["active"] is True


def test_neuron_activity_store_record_run_activity_alias(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    store = NeuronActivityStore(db_path=db_path)

    activity = {
        "active": True,
        "count": 1,
        "activations": [
            {
                "neuron_id": None,
                "name": "neurona-alias-test",
                "status": "experimental",
                "domain": "system_governance",
                "active": True,
                "output": {
                    "diagnosis": ["d1"],
                    "test_plan": [],
                },
                "policy": "experimental_neuron_no_external_actions_no_stable_memory_write",
            }
        ],
    }

    ids = store.record_run_activity("run-alias-test", activity)

    assert len(ids) == 1
    rows = store.list_activity(name="neurona-alias-test")
    assert rows[0]["diagnosis_count"] == 1


def test_neuron_activity_store_ignores_inactive_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    store = NeuronActivityStore(db_path=db_path)

    ids = store.store_activity(run_id="run-inactive", activity={"active": False, "activations": []})

    assert ids == []
    assert store.list_activity() == []
