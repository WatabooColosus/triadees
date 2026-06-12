from triade.qualia.contracts import (
    CentralKnowledgePacket,
    NeuronExperience,
    QualiaSignal,
    QualiaState,
    StorageMemoryPacket,
    new_qualia_id,
)


def test_neuron_experience_defaults_and_dict() -> None:
    exp = NeuronExperience(run_id="run-q", neuron_type="experimental", observation="observa")
    payload = exp.to_dict()
    assert exp.id.startswith("qexp-")
    assert payload["run_id"] == "run-q"
    assert payload["risk"] == "low"


def test_qualia_state_dict() -> None:
    state = QualiaState(run_id="run-q", curiosity=0.5, dominant_signal="learning_candidate")
    assert state.to_dict()["dominant_signal"] == "learning_candidate"


def test_new_qualia_id_prefix() -> None:
    assert new_qualia_id("qexp").startswith("qexp-")
    assert new_qualia_id("qsig").startswith("qsig-")
    assert new_qualia_id("qcen").startswith("qcen-")
    assert new_qualia_id("qmem").startswith("qmem-")


def test_qualia_signal_defaults() -> None:
    sig = QualiaSignal(run_id="run-s")
    assert sig.id.startswith("qsig-")
    assert sig.signal_type == "observation"
    assert sig.intensity == 0.0
    assert sig.tone_hint == "constructive"


def test_central_knowledge_packet_defaults() -> None:
    pkt = CentralKnowledgePacket(run_id="run-c")
    assert pkt.id.startswith("qcen-")
    assert pkt.status == "hypothesis"
    assert pkt.validation_need == "verify_before_use"


def test_storage_memory_packet_defaults() -> None:
    pkt = StorageMemoryPacket(run_id="run-m")
    assert pkt.id.startswith("qmem-")
    assert pkt.memory_type == "candidate"
    assert pkt.verification_status == "unverified"
    assert pkt.promotion_status == "candidate"


def test_neuron_experience_full_dict() -> None:
    exp = NeuronExperience(
        run_id="run-full",
        neuron_id=42,
        neuron_type="test",
        mission="misión test",
        observation="obs test",
        extracted_pattern="patrón",
        proposed_learning="aprender",
        confidence=0.9,
        risk="high",
        usefulness=0.8,
        emotional_signal={"valence": 0.3},
        evidence_refs=["ref1", "ref2"],
    )
    d = exp.to_dict()
    assert d["neuron_id"] == 42
    assert d["confidence"] == 0.9
    assert len(d["evidence_refs"]) == 2
