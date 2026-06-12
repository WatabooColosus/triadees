from triade.qualia.state import compute_qualia_state


def test_state_recommends_learning_review() -> None:
    state = compute_qualia_state(
        "run-state",
        signals=[{"signal_type": "learning_candidate", "risk": 0.2, "urgency": 0.3, "confidence": 0.8, "curiosity": 0.8}],
        experiences=[{"usefulness": 0.7, "proposed_learning": "aprende"}],
    )
    assert state.dominant_signal == "learning_candidate"
    assert state.recommended_action == "review_learning_candidates"


def test_state_recommends_safety_review_on_high_risk() -> None:
    state = compute_qualia_state(
        "run-risk",
        signals=[{"signal_type": "observation", "risk": 0.85, "urgency": 0.3, "confidence": 0.5, "curiosity": 0.4}],
        experiences=[],
    )
    assert state.recommended_action == "review_safety"
    assert state.risk >= 0.75


def test_state_observes_on_low_curiosity() -> None:
    state = compute_qualia_state(
        "run-obs",
        signals=[{"signal_type": "observation", "risk": 0.1, "urgency": 0.1, "confidence": 0.5, "curiosity": 0.2}],
        experiences=[{"usefulness": 0.3}],
    )
    assert state.recommended_action == "observe"


def test_state_empty_signals() -> None:
    state = compute_qualia_state("run-empty", signals=[], experiences=[])
    assert state.dominant_signal == "none"
    assert state.recommended_action == "observe"
    assert state.curiosity == 0.0


def test_state_saturation_increases_with_signal_count() -> None:
    many_signals = [
        {"signal_type": "observation", "risk": 0.1, "urgency": 0.1, "confidence": 0.5, "curiosity": 0.5}
        for _ in range(15)
    ]
    state = compute_qualia_state("run-sat", signals=many_signals, experiences=[])
    assert state.saturation > 0.0
    assert state.novelty > 0.0


def test_state_coherence_range() -> None:
    state = compute_qualia_state(
        "run-coh",
        signals=[{"signal_type": "observation", "risk": 0.5, "urgency": 0.5, "confidence": 0.8, "curiosity": 0.6}],
        experiences=[{"usefulness": 0.7}],
    )
    assert 0.0 <= state.coherence <= 1.0
