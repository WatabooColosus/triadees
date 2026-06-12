from triade.qualia.contracts import NeuronExperience
from triade.qualia.router import QualiaRouter


def test_router_generates_signal_central_storage_and_learning() -> None:
    exp = NeuronExperience(
        run_id="run-q",
        neuron_type="experimental_neuron",
        mission="vigilar memoria",
        observation="hay patrón útil",
        extracted_pattern="patrón",
        proposed_learning="aprender patrón",
        confidence=0.8,
        risk="medium",
        usefulness=0.7,
        evidence_refs=["run:run-q"],
    )
    bundle = QualiaRouter().route(exp)
    assert bundle.signal.experience_id == exp.id
    assert bundle.central_packet.status == "hypothesis"
    assert bundle.storage_packet.promotion_status == "candidate"
    assert bundle.learning_candidate is not None
    assert bundle.learning_candidate["source_type"] == "qualia_bus"


def test_router_no_learning_without_proposed_learning() -> None:
    exp = NeuronExperience(run_id="run-nl", observation="obs", proposed_learning="")
    bundle = QualiaRouter().route(exp)
    assert bundle.learning_candidate is None


def test_router_signal_intensity_from_confidence() -> None:
    exp = NeuronExperience(run_id="run-int", confidence=0.9, usefulness=0.5, risk="low")
    signal = QualiaRouter().to_signal(exp)
    assert signal.intensity >= 0.5


def test_router_high_risk_sets_cautious_tone() -> None:
    exp = NeuronExperience(run_id="run-risk", risk="critical")
    signal = QualiaRouter().to_signal(exp)
    assert signal.tone_hint == "cautious"


def test_router_central_verified_when_high_confidence_low_risk() -> None:
    exp = NeuronExperience(run_id="run-vc", confidence=0.9, risk="low", extracted_pattern="patrón claro")
    central = QualiaRouter().to_central_packet(exp)
    assert central.status == "verified_context"
    assert central.validation_need == "verified_context_allowed"


def test_router_central_hypothesis_when_medium_confidence() -> None:
    exp = NeuronExperience(run_id="run-hyp", confidence=0.5, risk="medium")
    central = QualiaRouter().to_central_packet(exp)
    assert central.status == "hypothesis"
    assert central.validation_need == "verify_before_use"


def test_router_storage_content_hash() -> None:
    exp = NeuronExperience(run_id="run-hash", mission="test", observation="obs", extracted_pattern="pat")
    storage = QualiaRouter().to_storage_packet(exp)
    assert len(storage.content_hash) == 64


def test_router_storage_empty_content_no_hash() -> None:
    exp = NeuronExperience(run_id="run-empty", mission="", observation="", extracted_pattern="", proposed_learning="")
    storage = QualiaRouter().to_storage_packet(exp)
    assert storage.content_hash == ""
