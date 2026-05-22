"""Tests de Crystal v2, Q_cristal y continuidad temporal 1.8D."""

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
    crystal = Crystal().regulate(stable_signals(), MemoryPacket(run_id="run-test", confidence=0.75))
    payload = crystal.to_dict()

    assert payload["pv7_score"] > 0
    assert payload["stability"] > 0
    assert payload["intensity"] > 0
    assert payload["q_crystal"] > 0
    assert payload["temporal_status"] == "baseline"
    assert payload["history_window"] == 0
    assert "ethics_vector" in payload
    assert "regulation_notes" in payload
    assert "q_crystal=" in " ".join(payload["decision_notes"])
    assert "s_rel=" in " ".join(payload["decision_notes"])
    assert "phi_memory=" in " ".join(payload["decision_notes"])
    assert "temporal_status=" in " ".join(payload["decision_notes"])


def test_q_crystal_payload_exposes_formula_components() -> None:
    payload = Crystal.q_crystal_payload(
        ethics=0.9, depth=0.8, creativity=0.55, relation=0.82,
        pv7_score=0.8, stability=0.85, intensity=0.3,
        memory_confidence=0.8, risk="low",
    )
    assert 0 <= payload["q_crystal"] <= 1
    assert set(["s_h", "s_t", "s_rel", "alpha", "beta", "c_prime", "i_prime", "r_prime", "phi_memory"]).issubset(payload)
    assert round(payload["alpha"] + payload["beta"], 3) == 1.0


def test_q_crystal_decreases_under_critical_risk() -> None:
    safe = Crystal.q_crystal_payload(0.9, 0.8, 0.55, 0.8, 0.8, 0.85, 0.25, 0.8, "low")
    critical = Crystal.q_crystal_payload(0.9, 0.8, 0.35, 0.8, 0.8, 0.4, 1.0, 0.8, "critical")
    assert safe["q_crystal"] > critical["q_crystal"]
    assert critical["i_prime"] > safe["i_prime"]


def test_temporal_state_detects_degrading_and_improving() -> None:
    history = [{"q_crystal": 0.72, "stability": 0.80}]
    degrading = Crystal.temporal_state(q_crystal=0.48, stability=0.58, history=history)
    improving = Crystal.temporal_state(q_crystal=0.84, stability=0.90, history=history)

    assert degrading["status"] == "degrading"
    assert degrading["q_delta"] < 0
    assert improving["status"] == "improving"
    assert improving["q_delta"] > 0


def test_central_plan_uses_crystal_and_temporal_regulation() -> None:
    central = Central()
    input_packet = InputPacket(user_input="Analiza", run_id="run-central")
    signals = stable_signals("run-central")
    memory = MemoryPacket(run_id="run-central", confidence=0.7)
    high_crystal = CrystalPacket(run_id="run-central", q_crystal=0.78, stability=0.82, temporal_status="stable")
    low_crystal = CrystalPacket(run_id="run-central", q_crystal=0.55, stability=0.58, temporal_status="degrading")

    high_plan = central.plan(input_packet, signals, memory, high_crystal)
    low_plan = central.plan(input_packet, signals, memory, low_crystal)

    assert "q_crystal=0.78" in high_plan.goal
    assert "temporal=stable" in high_plan.goal
    assert any("Profundizar" in step for step in high_plan.steps)
    assert any("degradación temporal" in step for step in low_plan.steps)
    assert Central._crystal_mode(high_crystal) == "profundidad estable"
    assert Central._crystal_mode(low_crystal) == "prudencia temporal reforzada"


def test_crystal_v2_runner_artifact_contains_temporal_fields(tmp_path) -> None:
    db_path = tmp_path / "triade.db"
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=db_path, use_ollama=False)
    first = runner.run("Primera prueba de cristal temporal", source="test")
    second = runner.run("Segunda prueba de cristal temporal", source="test")

    first_payload = json.loads((tmp_path / "runs" / first["run_id"] / "crystal.json").read_text(encoding="utf-8"))
    second_payload = json.loads((tmp_path / "runs" / second["run_id"] / "crystal.json").read_text(encoding="utf-8"))

    assert first_payload["temporal_status"] == "baseline"
    assert second_payload["history_window"] >= 1
    assert "q_delta" in second_payload
    assert "crystal_temporal_state" in second["memory_diff"]
