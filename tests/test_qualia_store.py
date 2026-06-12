from pathlib import Path

from triade.qualia.contracts import NeuronExperience
from triade.qualia.router import QualiaRouter
from triade.qualia.store import QualiaStore


def test_store_persists_full_bundle(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    exp = NeuronExperience(run_id="run-store", observation="obs", proposed_learning="learn")
    bundle = QualiaRouter().route(exp)
    ids = store.persist_bundle(bundle)
    state_id = store.store_state(__import__("triade.qualia.state", fromlist=["compute_qualia_state"]).compute_qualia_state("run-store", store.list_signals("run-store"), store.list_experiences("run-store")))
    assert ids["experience_id"] == exp.id
    assert state_id >= 1
    assert store.counts("run-store")["qualia_experiences"] == 1
    assert store.list_experiences("run-store")[0]["evidence_refs"] == []
