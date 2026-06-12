from pathlib import Path

from triade.learning.pipeline import LearningPipeline
from triade.qualia.bus import QualiaBus
from triade.qualia.contracts import NeuronExperience


def test_learning_pipeline_accepts_qualia_bus_source(tmp_path: Path) -> None:
    pipe = LearningPipeline(db_path=tmp_path / "triade.db")
    candidate = pipe.ingest("Aprendizaje desde experiencia neuronal.", source_type="qualia_bus", source_ref="qualia:q1")
    assert candidate["status"] == "candidate"
    assert candidate["source_type"] == "qualia_bus"


def test_bus_does_not_promote_stable_memory(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    result = QualiaBus(db_path=db).publish_experience(NeuronExperience(run_id="run-l", proposed_learning="Solo candidato QualiaBus.", evidence_refs=["run:run-l"]))
    candidate_id = result["learning"]["candidate_id"]
    row = LearningPipeline(db_path=db).get_candidate(candidate_id)
    assert row["status"] == "candidate"


def test_bus_dedup_returns_existing_candidate(tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    bus = QualiaBus(db_path=db)
    exp = NeuronExperience(
        run_id="run-dedup2",
        proposed_learning="Contenido que no debe duplicarse.",
        evidence_refs=["run:run-dedup2"],
    )
    r1 = bus.publish_experience(exp)
    r2 = bus.publish_experience(exp)
    assert r1["learning"]["candidate_id"] == r2["learning"]["candidate_id"]
    assert r2["learning"].get("deduplicated") is True
    pipe = LearningPipeline(db_path=db)
    candidates = [
        c for c in pipe.list_candidates(status="candidate", limit=50)
        if c.get("source_ref") == f"qualia:{exp.id}"
    ]
    assert len(candidates) == 1


def test_learning_source_type_qualia_bus_accepted() -> None:
    from triade.learning.pipeline import VALID_SOURCE_TYPES
    assert "qualia_bus" in VALID_SOURCE_TYPES
