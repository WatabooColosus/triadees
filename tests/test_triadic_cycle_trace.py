from __future__ import annotations

import json
from pathlib import Path

from triade.core.contracts import (
    CrystalPacket,
    InputPacket,
    MemoryPacket,
    OutputPacket,
    PlanPacket,
    SafetyPacket,
    SignalPacket,
)
from triade.core.triadic_cycle import (
    build_triadic_cycle_trace,
    verify_triadic_cycle_trace,
)
from triade.evaluation.triadic_ablation import run_triadic_ablation_benchmark


def _trace():
    packet = InputPacket(user_input="trace", run_id="run-trace")
    signals = SignalPacket(
        run_id=packet.run_id,
        intent="analyze",
        tone="calm",
        urgency="low",
        risk="low",
    )
    memory = MemoryPacket(run_id=packet.run_id, confidence=0.8)
    crystal = CrystalPacket(run_id=packet.run_id, q_crystal=0.7)
    plan = PlanPacket(run_id=packet.run_id, goal="trace").to_dict()
    safety = SafetyPacket(run_id=packet.run_id, status="approved", risk_level="low")
    output = OutputPacket(run_id=packet.run_id, response="traced")
    return build_triadic_cycle_trace(
        input_packet=packet,
        signals=signals,
        memory=memory,
        crystal=crystal,
        plan=plan,
        safety=safety,
        output=output,
        hypothalamus_model_result={"provider": "rules", "name": "rules", "ok": False},
    )


def test_trace_has_verifiable_causal_references() -> None:
    trace = _trace()
    result = verify_triadic_cycle_trace(trace)

    assert result["status"] == "verified"
    assert set(trace.component_contribution) == {
        "hypothalamus",
        "bodega",
        "crystal",
        "central",
        "safety",
    }


def test_trace_tamper_is_detected() -> None:
    trace = _trace()
    trace.memory_recalled["confidence"] = 0.1

    result = verify_triadic_cycle_trace(trace)

    assert result["status"] == "failed"
    assert result["invalid_references"]


def test_runner_writes_trace_for_every_run(tmp_path: Path) -> None:
    from triade.core.runner import TriadeRunner

    result = TriadeRunner(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
        use_ollama=False,
    ).run("Explica el estado de identidad", semantic_recall_enabled=False)
    run_path = Path(result["run_path"])
    trace = json.loads((run_path / "triadic_cycle_trace.json").read_text())
    verification = json.loads(
        (run_path / "triadic_cycle_trace_verification.json").read_text()
    )

    assert trace["run_id"] == result["run_id"]
    assert verification["status"] == "verified"
    assert result["triadic_cycle_trace"]["trace_version"] == "TRIADIC-CYCLE-TRACE-v1"


def test_deterministic_ablation_demonstrates_each_removal(tmp_path: Path) -> None:
    result = run_triadic_ablation_benchmark(tmp_path / "ablation.db")

    assert result["passed"] is True
    assert all(result["contribution_demonstrated"].values())
    assert result["model_calls"] is False
