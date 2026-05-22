"""Tests de retroalimentación Crystal → Safety → Verifier 1.8E."""

from __future__ import annotations

from triade.core.contracts import CrystalPacket, OutputPacket, PlanPacket, SignalPacket
from triade.core.safety import Safety
from triade.core.verification import Verifier


def signals(run_id: str = "run-safety") -> SignalPacket:
    return SignalPacket(
        run_id=run_id,
        intent="conversation",
        tone="constructive",
        urgency="medium",
        risk="low",
        pv7={},
    )


def plan(run_id: str = "run-safety", tools: list[str] | None = None) -> PlanPacket:
    return PlanPacket(run_id=run_id, goal="Validar feedback Crystal", tools=tools or [])


def degrading_crystal(run_id: str = "run-safety") -> CrystalPacket:
    return CrystalPacket(
        run_id=run_id,
        q_crystal=0.52,
        stability=0.57,
        q_delta=-0.18,
        stability_delta=-0.17,
        temporal_status="degrading",
        temporal_alerts=["Degradación temporal detectada."],
    )


def critical_crystal(run_id: str = "run-safety") -> CrystalPacket:
    return CrystalPacket(
        run_id=run_id,
        q_crystal=0.22,
        stability=0.29,
        q_delta=-0.31,
        stability_delta=-0.26,
        temporal_status="critical",
        temporal_alerts=["Umbral crítico detectado."],
    )


def output(run_id: str = "run-safety") -> OutputPacket:
    return OutputPacket(
        run_id=run_id,
        response="Respuesta verificable de prueba.",
        memory_diff={"stored": True, "episode_id": 1, "signal_id": 1, "crystal_id": 1, "safety_id": 1},
    )


def test_safety_warns_on_degrading_crystal_without_tools() -> None:
    safety = Safety().review(signals(), plan(), crystal=degrading_crystal())

    assert safety.status == "approved_with_warning"
    assert safety.risk_level == "medium"
    assert "cognitive_temporal" in safety.risk_types
    assert safety.human_approval_required is False
    assert any("Cristal" in control for control in safety.required_controls)


def test_safety_requires_human_approval_for_tools_during_degradation() -> None:
    safety = Safety().review(
        signals(),
        plan(tools=["repository_or_file_update"]),
        crystal=degrading_crystal(),
    )

    assert safety.status == "requires_human_approval"
    assert safety.human_approval_required is True
    assert "cognitive_temporal" in safety.risk_types
    assert any("aprobación humana" in control for control in safety.required_controls)


def test_safety_raises_level_on_critical_crystal() -> None:
    safety = Safety().review(signals(), plan(), crystal=critical_crystal())

    assert safety.status == "approved_with_warning"
    assert safety.risk_level == "high"
    assert "cognitive_temporal" in safety.risk_types


def test_verifier_reflects_degrading_crystal() -> None:
    crystal = degrading_crystal()
    safety = Safety().review(signals(), plan(), crystal=crystal)
    report = Verifier().verify(output(), safety, crystal=crystal)

    assert report.status == "warning"
    assert report.coherence_score <= 0.60
    assert report.safety_score <= 0.65
    assert any("degradación temporal" in warning for warning in report.warnings)
    assert any("cambios estructurales" in item for item in report.recommendations)


def test_verifier_reflects_critical_crystal() -> None:
    crystal = critical_crystal()
    safety = Safety().review(signals(), plan(), crystal=crystal)
    report = Verifier().verify(output(), safety, crystal=crystal)

    assert report.status == "warning"
    assert report.coherence_score <= 0.35
    assert report.safety_score <= 0.40
    assert any("estado temporal crítico" in warning for warning in report.warnings)
    assert any("revisión humana" in item for item in report.recommendations)
