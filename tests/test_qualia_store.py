from pathlib import Path

from triade.qualia.contracts import NeuronExperience, QualiaSignal, CentralKnowledgePacket, StorageMemoryPacket, QualiaState
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


def test_store_experience_crud(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    exp = NeuronExperience(run_id="run-crud", observation="obs CRUD")
    store.store_experience(exp)
    rows = store.list_experiences(run_id="run-crud")
    assert len(rows) == 1
    assert rows[0]["id"] == exp.id
    assert rows[0]["run_id"] == "run-crud"


def test_store_signal_crud(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    sig = QualiaSignal(run_id="run-sig", experience_id="qexp-test", intensity=0.8)
    store.store_signal(sig)
    rows = store.list_signals(run_id="run-sig")
    assert len(rows) == 1
    assert rows[0]["intensity"] == 0.8


def test_store_central_packet_crud(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    pkt = CentralKnowledgePacket(run_id="run-cen", claim="claim test", hypothesis="hyp test")
    store.store_central_packet(pkt)
    rows = store.list_central_packets(run_id="run-cen")
    assert len(rows) == 1
    assert rows[0]["claim"] == "claim test"


def test_store_storage_packet_crud(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    pkt = StorageMemoryPacket(run_id="run-sto", content="content test", content_hash="abc123")
    store.store_storage_packet(pkt)
    rows = store.list_storage_packets(run_id="run-sto")
    assert len(rows) == 1
    assert rows[0]["content_hash"] == "abc123"


def test_store_state_persistence(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    state = QualiaState(run_id="run-state", curiosity=0.7, risk=0.3, recommended_action="observe")
    store.store_state(state)
    latest = store.latest_state(run_id="run-state")
    assert latest is not None
    assert latest["curiosity"] == 0.7
    assert latest["recommended_action"] == "observe"


def test_store_counts(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    exp1 = NeuronExperience(run_id="run-counts", observation="obs1")
    exp2 = NeuronExperience(run_id="run-counts", observation="obs2")
    store.store_experience(exp1)
    store.store_experience(exp2)
    counts = store.counts(run_id="run-counts")
    assert counts["qualia_experiences"] == 2
    assert counts["qualia_signals"] == 0


def test_store_doctor(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    doctor = store.doctor()
    assert doctor["status"] == "ok"
    assert doctor["missing_tables"] == []


def test_store_list_without_run_id(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    exp1 = NeuronExperience(run_id="run-a", observation="obs a")
    exp2 = NeuronExperience(run_id="run-b", observation="obs b")
    store.store_experience(exp1)
    store.store_experience(exp2)
    all_exp = store.list_experiences(limit=100)
    assert len(all_exp) >= 2


def test_store_central_packet_filter_by_status(tmp_path: Path) -> None:
    store = QualiaStore(db_path=tmp_path / "triade.db")
    h = CentralKnowledgePacket(run_id="run-fil", status="hypothesis")
    v = CentralKnowledgePacket(run_id="run-fil", status="verified_context")
    store.store_central_packet(h)
    store.store_central_packet(v)
    hyp_only = store.list_central_packets(run_id="run-fil", statuses={"hypothesis"})
    assert len(hyp_only) == 1
    assert hyp_only[0]["status"] == "hypothesis"
