"""Tests del Cristal Morfológico 1.2B."""

from __future__ import annotations

from triade.core.contracts import MemoryPacket, SignalPacket
from triade.core.crystal import Crystal


def make_signal(risk: str = "low", urgency: str = "medium") -> SignalPacket:
    return SignalPacket(
        run_id="run-test-crystal",
        intent="conversation",
        tone="constructive",
        urgency=urgency,  # type: ignore[arg-type]
        risk=risk,  # type: ignore[arg-type]
        pv7={
            "humildad": 0.8,
            "generosidad": 0.7,
            "respeto": 0.9,
            "paciencia": 0.7,
            "templanza": 0.8,
            "caridad": 0.7,
            "diligencia": 0.9,
        },
    )


def test_crystal_calculates_internal_metrics() -> None:
    crystal = Crystal()
    signal = make_signal()
    memory = MemoryPacket(run_id="run-test-crystal", confidence=0.8)

    pv7 = crystal.pv7_score(signal)
    intensity = crystal.intensity(signal)
    stability = crystal.stability(signal, memory, pv7)

    assert 0.0 <= pv7 <= 1.0
    assert 0.0 <= intensity <= 1.0
    assert 0.0 <= stability <= 1.0
    assert pv7 >= 0.75


def test_crystal_regulate_adds_trace_notes() -> None:
    crystal = Crystal()
    signal = make_signal()
    memory = MemoryPacket(run_id="run-test-crystal", confidence=0.8)

    packet = crystal.regulate(signal, memory)

    assert packet.run_id == signal.run_id
    assert 0.0 <= packet.ethics <= 1.0
    assert 0.0 <= packet.depth <= 1.0
    assert 0.0 <= packet.creativity <= 1.0
    assert 0.0 <= packet.relation <= 1.0
    assert any("pv7_score=" in note for note in packet.decision_notes)
    assert any("stability=" in note for note in packet.decision_notes)
    assert any("intensity=" in note for note in packet.decision_notes)


def test_crystal_high_risk_prioritizes_control() -> None:
    crystal = Crystal()
    signal = make_signal(risk="high", urgency="high")
    memory = MemoryPacket(run_id="run-test-crystal", confidence=0.8)

    packet = crystal.regulate(signal, memory)

    assert packet.ethics >= 0.95
    assert packet.creativity <= 0.35
    assert any("control" in note.lower() for note in packet.decision_notes)
