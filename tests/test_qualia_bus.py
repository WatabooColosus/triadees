from pathlib import Path

from triade.qualia.bus import QualiaBus
from triade.qualia.contracts import NeuronExperience


def test_bus_publishes_and_ingests_learning_candidate(tmp_path: Path) -> None:
    bus = QualiaBus(db_path=tmp_path / "triade.db")
    exp = NeuronExperience(
        run_id="run-bus",
        neuron_type="test_neuron",
        observation="observación",
        proposed_learning="Contenido verificable desde QualiaBus con fuente y evidencia suficiente.",
        confidence=0.8,
        usefulness=0.8,
        evidence_refs=["run:run-bus"],
    )
    result = bus.publish_experience(exp)
    assert result["status"] == "ok"
    assert result["learning"]["source_type"] == "qualia_bus"
    assert result["state"]["run_id"] == "run-bus"
