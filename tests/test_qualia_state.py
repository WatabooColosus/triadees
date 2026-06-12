from triade.qualia.state import compute_qualia_state


def test_state_recommends_learning_review() -> None:
    state = compute_qualia_state(
        "run-state",
        signals=[{"signal_type": "learning_candidate", "risk": 0.2, "urgency": 0.3, "confidence": 0.8, "curiosity": 0.8}],
        experiences=[{"usefulness": 0.7, "proposed_learning": "aprende"}],
    )
    assert state.dominant_signal == "learning_candidate"
    assert state.recommended_action == "review_learning_candidates"
