from triade.qualia.contracts import NeuronExperience, QualiaState


def test_neuron_experience_defaults_and_dict() -> None:
    exp = NeuronExperience(run_id="run-q", neuron_type="experimental", observation="observa")
    payload = exp.to_dict()
    assert exp.id.startswith("qexp-")
    assert payload["run_id"] == "run-q"
    assert payload["risk"] == "low"


def test_qualia_state_dict() -> None:
    state = QualiaState(run_id="run-q", curiosity=0.5, dominant_signal="learning_candidate")
    assert state.to_dict()["dominant_signal"] == "learning_candidate"
