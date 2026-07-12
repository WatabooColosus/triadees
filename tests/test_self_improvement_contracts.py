import pytest

from triade.self_improvement import ImprovementProposal, ImprovementSignal


def test_signal_priority_is_deterministic() -> None:
    signal = ImprovementSignal(
        signal_id="signal-1",
        capability_id="research_verified",
        metric_id="quality",
        observed_score=0.60,
        target_score=0.80,
        impact=0.90,
        confidence=0.80,
        estimated_cost=2.0,
        risk_level="medium",
    )

    assert signal.priority() == pytest.approx(0.0576)
    assert signal.to_dict()["priority"] == pytest.approx(0.0576)


def test_signal_rejects_non_improving_target() -> None:
    signal = ImprovementSignal(
        signal_id="signal-1",
        capability_id="research_verified",
        metric_id="quality",
        observed_score=0.80,
        target_score=0.80,
        impact=0.90,
        confidence=0.80,
        estimated_cost=2.0,
    )

    with pytest.raises(ValueError, match="target_score"):
        signal.validate()


def test_high_risk_signal_is_penalized() -> None:
    common = dict(
        signal_id="signal-1",
        capability_id="research_verified",
        metric_id="quality",
        observed_score=0.60,
        target_score=0.80,
        impact=1.0,
        confidence=1.0,
        estimated_cost=1.0,
    )
    low = ImprovementSignal(**common, risk_level="low")
    high = ImprovementSignal(**common, risk_level="high")

    assert high.priority() < low.priority()


def test_proposal_enforces_candidate_limit() -> None:
    proposal = ImprovementProposal(
        proposal_id="proposal-1",
        signal_id="signal-1",
        hypothesis="una nueva configuración mejora calidad",
        requested_capability="research_verified",
        requires_human_approval=True,
        max_candidates=0,
    )

    with pytest.raises(ValueError, match="max_candidates"):
        proposal.validate()
