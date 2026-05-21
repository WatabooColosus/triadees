"""Tests de Crystal v2 1.8A."""

from __future__ import annotations

import json

from triade.core.contracts import MemoryPacket, SignalPacket
from triade.core.crystal import Crystal
from triade.core.runner import TriadeRunner


def test_crystal_v2_outputs_real_fields() -> None:
    signals = SignalPacket(
        run_id="run-test",
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
