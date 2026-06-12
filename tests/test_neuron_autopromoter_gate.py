from __future__ import annotations

from pathlib import Path

from triade.core.neuron_autopromoter import NeuronAutopromoter
from triade.core.neuron_creator import NeuronSpec
from triade.core.neuron_registry import NeuronRegistry


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
