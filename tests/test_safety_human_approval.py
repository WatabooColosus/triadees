"""Tests para Safety requires_human_approval."""

from __future__ import annotations

from triade.core.contracts import (
    CrystalPacket,
    MemoryPacket,
    PlanPacket,
    SafetyPacket,
    SignalPacket,
)
from triade.core.safety import Safety


def _make_signals(risk: str = "low", intent: str = "conversation") -> SignalPacket:
    return SignalPacket(
        run_id="test-run",
        intent=intent,
        tone="neutral",
        urgency="low",
        risk=risk,
        notes=[],
    )


def _make_plan(tools: list[str] | None = None) -> PlanPacket:
    return PlanPacket(
        run_id="test-run",
        goal="test goal",
        steps=["step1"],
        tools=tools or [],
    )


def _make_crystal(temporal_status: str = "stable") -> CrystalPacket:
    return CrystalPacket(
        run_id="test-run",
        q_delta=0.0,
        stability_delta=0.0,
        temporal_status=temporal_status,
    )


def _make_memory(quarantined: int = 0) -> MemoryPacket:
    return MemoryPacket(
        run_id="test-run",
        identity_matches=[],
        semantic_matches=[],
        episodic_matches=[],
        semantic_recall={
            "governance": {
                "quarantined_vector_matches": quarantined,
                "allowed_vector_matches": 0,
            }
        },
    )


def test_critical_risk_produces_requires_human_approval():
    signals = _make_signals(risk="critical")
    plan = _make_plan()
    safety = Safety()
    result = safety.review(signals, plan)
    assert result.status == "requires_human_approval"
    assert result.human_approval_required is True
    assert result.risk_level == "critical"
    assert "critical_risk" in result.risk_types


def test_sandbox_only_still_works():
    signals = _make_signals(risk="low")
    plan = _make_plan(tools=["git"])
    safety = Safety()
    result = safety.review(signals, plan)
    assert result.status == "sandbox_only"
    assert result.human_approval_required is False


def test_blocked_still_blocks():
    signals = _make_signals(risk="low")
    plan = _make_plan(tools=["rm -rf /"])
    safety = Safety()
    result = safety.review(signals, plan)
    assert result.status == "blocked"
    assert result.human_approval_required is False


def test_approved_simple_still_approved():
    signals = _make_signals(risk="low")
    plan = _make_plan()
    safety = Safety()
    result = safety.review(signals, plan)
    assert result.status == "approved"
    assert result.human_approval_required is False


def test_quarantined_memory_with_tools_requires_human_approval():
    signals = _make_signals(risk="low")
    plan = _make_plan(tools=["read_file"])
    memory = _make_memory(quarantined=3)
    safety = Safety()
    result = safety.review(signals, plan, memory=memory)
    assert result.status == "requires_human_approval"
    assert result.human_approval_required is True
    assert "semantic_memory_unverified" in result.risk_types


def test_quarantined_memory_without_tools_does_not_require_approval():
    signals = _make_signals(risk="low")
    plan = _make_plan(tools=[])
    memory = _make_memory(quarantined=3)
    safety = Safety()
    result = safety.review(signals, plan, memory=memory)
    assert result.status == "approved_with_warning"
    assert result.human_approval_required is False


def test_crITICAL_crystal_with_repo_tools_requires_human_approval():
    signals = _make_signals(risk="low")
    plan = _make_plan(tools=["read_file"])
    crystal = _make_crystal(temporal_status="critical")
    safety = Safety()
    result = safety.review(signals, plan, crystal=crystal)
    assert result.status == "approved_with_warning"
    assert result.human_approval_required is False


def test_degrading_crystal_with_tools_warning():
    signals = _make_signals(risk="low")
    plan = _make_plan(tools=["read_file"])
    crystal = _make_crystal(temporal_status="degrading")
    safety = Safety()
    result = safety.review(signals, plan, crystal=crystal)
    assert result.status == "approved_with_warning"
    assert result.human_approval_required is False


def test_high_risk_not_blocked_gets_warning():
    signals = _make_signals(risk="high")
    plan = _make_plan()
    safety = Safety()
    result = safety.review(signals, plan)
    assert result.status == "approved_with_warning"
    assert result.human_approval_required is False
