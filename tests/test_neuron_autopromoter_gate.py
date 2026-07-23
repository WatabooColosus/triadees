from __future__ import annotations

from pathlib import Path

from triade.core.neuron_autopromoter import NeuronAutopromoter
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.core.neuron_registry import NeuronRegistry
from triade.core.neuron_trainer import NeuronTrainingResult


def test_candidate_gate_blocks_candidate_to_experimental_promotion(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)
    registry.register(
        NeuronSpec(
            name="neurona-literalista",
            mission="¿En qué continente queda Colombia?",
            domain="general",
            status="candidate",
            created_by="test",
        ),
        contract_payload={
            "candidate_gate": {
                "score": 0.15,
                "detected_type": "factual_simple",
                "route": "learning_candidate",
            }
        },
    )

    events = NeuronAutopromoter(db_path=db_path).promote()

    assert any(event.get("reason") == "blocked_by_neuron_candidate_gate" for event in events)
    neuron = registry.get_neuron("neurona-literalista")
    assert neuron is not None
    assert neuron["status"] == "candidate"


def test_candidate_promotion_keeps_mission_lifecycle_in_sync(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    registry = NeuronRegistry(db_path=db_path)
    neuron_id = registry.register(
        NeuronSpec(
            name="neurona-auditora",
            mission="Auditar repetidamente la coherencia del runtime con evidencia verificable.",
            domain="system_governance",
            status="candidate",
            created_by="test",
        ),
        contract_payload={"activation_policy": {"auto_approve": True}},
    )
    registry.store_training(
        neuron_id,
        NeuronTrainingResult(
            name="neurona-auditora",
            score=0.9,
            status="candidate",
            policy="test",
        ),
    )
    missions = NeuronMissionStore(db_path=db_path)
    mission_id = missions.create_mission(
        NeuronMission(
            neuron_id=neuron_id,
            title="Auditoría",
            mission="Auditar el runtime.",
            status="candidate",
        )
    )

    events = NeuronAutopromoter(db_path=db_path).promote()

    assert any(event.get("status") == "promoted" for event in events)
    assert registry.get_neuron("neurona-auditora")["status"] == "experimental"
    assert missions.get_mission(mission_id).status == "experimental"
