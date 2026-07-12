from dataclasses import replace
from pathlib import Path

import pytest

from triade.self_improvement import ImprovementProposal, ImprovementSignal, ImprovementStore


class Clock:
    def __init__(self, value: float = 1000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def signal(*, risk_level: str = "low") -> ImprovementSignal:
    return ImprovementSignal(
        signal_id="signal-quality",
        capability_id="research_verified",
        metric_id="quality",
        observed_score=0.60,
        target_score=0.80,
        impact=0.90,
        confidence=0.80,
        estimated_cost=2.0,
        risk_level=risk_level,
    )


def proposal(proposal_id: str = "proposal-1", *, approval: bool = False) -> ImprovementProposal:
    return ImprovementProposal(
        proposal_id=proposal_id,
        signal_id="signal-quality",
        hypothesis="una configuración nueva mejora calidad",
        requested_capability="research_verified",
        requires_human_approval=approval,
        max_candidates=1,
        cooldown_seconds=60,
    )


def test_signal_is_persisted_with_history(tmp_path: Path) -> None:
    store = ImprovementStore(tmp_path / "triade.db")

    registered = store.register_signal(signal())

    assert registered["status"] == "open"
    assert registered["priority"] > 0
    assert [event["action"] for event in store.history("signal-quality")] == ["registered"]


def test_duplicate_open_signal_is_rejected(tmp_path: Path) -> None:
    store = ImprovementStore(tmp_path / "triade.db")
    store.register_signal(signal())
    duplicate = replace(signal(), signal_id="signal-quality-2")

    with pytest.raises(ValueError, match="ya existe una señal abierta"):
        store.register_signal(duplicate)


def test_high_risk_proposal_requires_human_approval(tmp_path: Path) -> None:
    store = ImprovementStore(tmp_path / "triade.db")
    store.register_signal(signal(risk_level="high"))

    with pytest.raises(ValueError, match="aprobación humana"):
        store.create_proposal(proposal())

    created = store.create_proposal(proposal(approval=True))
    assert created["requires_human_approval"] is True


def test_cooldown_blocks_repeated_proposal(tmp_path: Path) -> None:
    clock = Clock()
    store = ImprovementStore(tmp_path / "triade.db", max_open_proposals=2, clock=clock)
    store.register_signal(signal())
    store.create_proposal(proposal())
    store.close_proposal("proposal-1", outcome="completed")

    clock.value += 30
    with pytest.raises(ValueError, match="cooldown"):
        store.create_proposal(proposal("proposal-2"))

    clock.value += 31
    assert store.create_proposal(proposal("proposal-2"))["status"] == "open"


def test_global_open_proposal_limit_is_enforced(tmp_path: Path) -> None:
    store = ImprovementStore(tmp_path / "triade.db", max_open_proposals=1)
    store.register_signal(signal())
    store.create_proposal(proposal())

    other_signal = ImprovementSignal(
        signal_id="signal-latency",
        capability_id="latency_control",
        metric_id="latency",
        observed_score=0.40,
        target_score=0.70,
        impact=0.80,
        confidence=0.80,
        estimated_cost=1.0,
    )
    store.register_signal(other_signal)
    other_proposal = ImprovementProposal(
        proposal_id="proposal-2",
        signal_id="signal-latency",
        hypothesis="una configuración reduce latencia",
        requested_capability="latency_control",
        requires_human_approval=False,
    )

    with pytest.raises(ValueError, match="límite global"):
        store.create_proposal(other_proposal)
