from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from triade.core.experimental_neuron_evidence import build_experimental_evidence_ledger
from triade.core.experimental_neuron_runtime import run_experimental_neurons
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry


def test_experimental_runtime_activates_only_experimental_neurons(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)

    registry.register(NeuronSpec(
        name="neurona-android-experimental",
        mission="Auditar nodo Android edge.",
        domain="federation_android_edge",
        rules=["Solo diagnóstico"],
        status="experimental",
        created_by="test",
    ))

    registry.register(NeuronSpec(
        name="neurona-android-candidate",
        mission="No debe activarse.",
        domain="federation_android_edge",
        rules=["No activar"],
        status="candidate",
        created_by="test",
    ))

    result = run_experimental_neurons(
        db_path=str(db_path),
        user_input="Verifica el nodo Android edge",
        context={},
        signals=SimpleNamespace(intent="analyze"),
        edge_usage={"used_edge": True, "accepted": True, "node_id": "local-test", "keywords": ["android", "edge"]},
        system_events=[],
    )

    assert result["active"] is True
    assert result["count"] == 1
    assert result["activations"][0]["name"] == "neurona-android-experimental"
    assert result["policy"]["can_modify_response"] is False
    assert result["policy"]["can_modify_repo"] is False
    assert result["policy"]["can_write_stable_memory"] is False
    assert result["policy"]["can_execute_external_actions"] is False


def test_experimental_runtime_does_not_activate_unmatched_domain(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)

    registry.register(NeuronSpec(
        name="neurona-android-experimental",
        mission="Auditar nodo Android edge.",
        domain="federation_android_edge",
        rules=["Solo diagnóstico"],
        status="experimental",
        created_by="test",
    ))

    result = run_experimental_neurons(
        db_path=str(db_path),
        user_input="Revisa memoria semántica",
        context={},
        signals=SimpleNamespace(intent="analyze"),
        edge_usage={"used_edge": False, "accepted": False, "keywords": ["memoria"]},
        system_events=[],
    )

    assert result["active"] is False
    assert result["count"] == 0


def test_experimental_evidence_ledger_counts_activations(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    run_path = runs_dir / "run-test-001"
    run_path.mkdir(parents=True)

    activity = {
        "active": True,
        "count": 1,
        "activations": [
            {
                "neuron_id": 16,
                "name": "neurona-verifica-estado-actual",
                "status": "experimental",
                "domain": "federation_android_edge",
                "match": {"active": True, "reasons": ["test"]},
                "output": {
                    "diagnosis": ["d1", "d2"],
                    "test_plan": ["t1", "t2", "t3"],
                },
                "policy": "experimental_neuron_no_external_actions_no_stable_memory_write",
            }
        ],
    }

    (run_path / "experimental_neuron_activity.json").write_text(
        json.dumps(activity, ensure_ascii=False),
        encoding="utf-8",
    )

    ledger = build_experimental_evidence_ledger(runs_dir=runs_dir, limit=10, prefer_db=False)

    assert ledger["summary"]["experimental_neurons_with_evidence"] == 1
    assert ledger["summary"]["total_activations"] == 1
    neuron = ledger["neurons"][0]
    assert neuron["name"] == "neurona-verifica-estado-actual"
    assert neuron["activation_count"] == 1
    assert neuron["diagnosis_count"] == 2
    assert neuron["test_plan_count"] == 3
    assert neuron["stable_promotion_ready"] is False
    assert "stable promotion requires separate human gate" in neuron["promotion_blockers"]
