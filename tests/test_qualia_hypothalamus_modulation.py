from triade.core.contracts import SignalPacket
from triade.core.hypothalamus import Hypothalamus


def test_hypothalamus_modulates_with_internal_qualia_signal() -> None:
    signals = SignalPacket(run_id="run-h", intent="conversation", tone="constructive", urgency="low", risk="low")
    modulated = Hypothalamus().apply_qualia_signals(signals, [{"intensity": 0.8, "risk": 0.75, "urgency": 0.8, "tone_hint": "cautious"}])
    assert modulated.risk == "high"
    assert modulated.urgency == "high"
    assert modulated.tone == "cautious"
    assert any("QualiaBus moduló" in note for note in modulated.notes)
