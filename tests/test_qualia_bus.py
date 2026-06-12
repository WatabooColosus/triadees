from pathlib import Path

from triade.learning.pipeline import LearningPipeline
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


def test_bus_deduplicates_learning_candidate(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    bus = QualiaBus(db_path=db)
    exp = NeuronExperience(
        run_id="run-dedup",
        neuron_type="test_neuron",
        observation="observación duplicada",
        proposed_learning="Contenido que no debe duplicarse en learning pipeline.",
        confidence=0.8,
        usefulness=0.8,
        evidence_refs=["run:run-dedup"],
    )
    result1 = bus.publish_experience(exp)
    result2 = bus.publish_experience(exp)
    assert result1["status"] == "ok"
    assert result2["status"] == "ok"
    pipe = LearningPipeline(db_path=db)
    candidates = [
        c for c in pipe.list_candidates(status="candidate", limit=50)
        if c.get("source_ref") == f"qualia:{exp.id}"
    ]
    assert len(candidates) == 1
    assert result2["learning"].get("deduplicated") is True


def test_bus_publishes_without_learning(tmp_path: Path) -> None:
    bus = QualiaBus(db_path=tmp_path / "triade.db")
    exp = NeuronExperience(
        run_id="run-nolearn",
        neuron_type="test_neuron",
        observation="sin aprendizaje propuesto",
        proposed_learning="",
        confidence=0.5,
    )
    result = bus.publish_experience(exp)
    assert result["status"] == "ok"
    assert result["learning"] is None
