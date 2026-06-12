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
