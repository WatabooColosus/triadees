"""Tests de Crystal v2 y Q_cristal 1.8C."""

from __future__ import annotations

import json

from triade.core.central import Central
from triade.core.contracts import CrystalPacket, InputPacket, MemoryPacket, SignalPacket
from triade.core.crystal import Crystal
from triade.core.runner import TriadeRunner


def stable_signals(run_id: str = "run-test") -> SignalPacket:
    return SignalPacket(
        run_id=run_id,
        intent="conversation",
        tone="constructive",
        urgency="medium",
        risk="low",
        pv7={
            "humildad": 0.8,
            "generosidad": 0.7,
            "respeto": 0.9,
            "paciencia": 0.8,
            "templanza": 0.7,
            "caridad": 0.8,
            "diligencia": 0.9,
        },
    )


def test_crystal_v2_outputs_real_fields() -> None:
    signals = stable_signals()
    memory = MemoryPacket(run_id="run-test", confidence=0.75)

    crystal = Crystal().regulate(signals, memory)
    payload = crystal.to_dict()

    assert payload["pv7_score"] > 0
    assert payload["stability"] > 0
    assert payload["intensity"] > 0
    assert payload["q_crystal"] > 0
    assert "ethics_vector" in payload
    assert "regulation_notes" in payload
    assert "q_crystal=" in " ".join(payload["decision_notes"])
    assert "s_rel=" in " ".join(payload["decision_notes"])
    assert "phi_memory=" in " ".join(payload["decision_notes"])


def test_q_crystal_payload_exposes_formula_components() -> None:
    payload = Crystal.q_crystal_payload(
        ethics=0.9,
        depth=0.8,
        creativity=0.55,
        relation=0.82,
        pv7_score=0.8,
        stability=0.85,
        intensity=0.3,
        memory_confidence=0.8,
        risk="low",
    )

    assert 0 <= payload["q_crystal"] <= 1
    assert set(["s_h", "s_t", "s_rel", "alpha", "beta", "c_prime", "i_prime", "r_prime", "phi_memory"]).issubset(payload)
    assert round(payload["alpha"] + payload["beta"], 3) == 1.0


def test_q_crystal_decreases_under_critical_risk() -> None:
    safe = Crystal.q_crystal_payload(0.9, 0.8, 0.55, 0.8, 0.8, 0.85, 0.25, 0.8, "low")
    critical = Crystal.q_crystal_payload(0.9, 0.8, 0.35, 0.8, 0.8, 0.4, 1.0, 0.8, "critical")

    assert safe["q_crystal"] > critical["q_crystal"]
    assert critical["i_prime"] > safe["i_prime"]


def test_central_plan_uses_crystal_regulation() -> None:
    central = Central()
    input_packet = InputPacket(user_input="Analiza", run_id="run-central")
    signals = stable_signals("run-central")
    memory = MemoryPacket(run_id="run-central", confidence=0.7)
    high_crystal = CrystalPacket(run_id="run-central", q_crystal=0.78, stability=0.82)
    low_crystal = CrystalPacket(run_id="run-central", q_crystal=0.25, stability=0.3)

    high_plan = central.plan(input_packet, signals, memory, high_crystal)
    low_plan = central.plan(input_packet, signals, memory, low_crystal)

    assert "q_crystal=0.78" in high_plan.goal
    assert any("Profundizar" in step for step in high_plan.steps)
    assert any("prudencia" in step for step in low_plan.steps)
    assert Central._crystal_mode(high_crystal) == "profundidad estable"
    assert Central._crystal_mode(low_crystal) == "prudencia elevada"


def test_crystal_v2_runner_artifact_contains_extended_fields(tmp_path) -> None:
    runner = TriadeRunner(runs_dir=tmp_path, use_ollama=False)
    result = runner.run("Prueba de cristal v2", source="test")

    crystal_path = tmp_path / result["run_id"] / "crystal.json"
    payload = json.loads(crystal_path.read_text(encoding="utf-8"))

    assert "pv7_score" in payload
    assert "stability" in payload
    assert "intensity" in payload
    assert "q_crystal" in payload
    assert "ethics_vector" in payload
    assert "regulation_notes" in payload
