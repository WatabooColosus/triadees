"""Tests para select_relevant_missions."""

from __future__ import annotations

from triade.core.neuron_missions import NeuronMission, select_relevant_missions


def _make_mission(
    title: str = "Test Mission",
    mission: str = "Test mission description",
    domain: str = "general",
    status: str = "candidate",
    metrics: dict | None = None,
) -> NeuronMission:
    return NeuronMission(
        neuron_id=1,
        title=title,
        mission=mission,
        domain=domain,
        status=status,
        metrics=metrics or {},
    )


def test_irrelevant_mission_not_selected():
    missions = [_make_mission(title="Deep Learning", mission="Train neural networks", domain="ml")]
    result = select_relevant_missions(missions, user_input="cooking recipes", domain="cooking")
    assert len(result) == 0


def test_same_domain_mission_selected():
    missions = [_make_mission(title="Data Analysis", mission="Analyze data patterns", domain="analytics")]
    result = select_relevant_missions(missions, user_input="", domain="analytics")
    assert len(result) == 1
    assert result[0].domain == "analytics"


def test_rejected_paused_not_selected():
    missions = [
        _make_mission(title="Active Mission", domain="test", status="candidate"),
        _make_mission(title="Rejected Mission", domain="test", status="rejected"),
        _make_mission(title="Paused Mission", domain="test", status="paused"),
    ]
    result = select_relevant_missions(missions, domain="test")
    assert len(result) == 1
    assert result[0].title == "Active Mission"


def test_stable_mission_selected():
    missions = [_make_mission(title="Stable Mission", domain="core", status="stable")]
    result = select_relevant_missions(missions, domain="core")
    assert len(result) == 1
    assert result[0].status == "stable"


def test_experimental_mission_selected():
    missions = [_make_mission(title="Exp Mission", domain="research", status="experimental")]
    result = select_relevant_missions(missions, domain="research")
    assert len(result) == 1
    assert result[0].status == "experimental"


def test_keyword_relevance_boosts_score():
    missions = [
        _make_mission(title="Memory System", mission="Manage memory consolidation", domain="general"),
        _make_mission(title="Network System", mission="Handle network connections", domain="general"),
    ]
    result = select_relevant_missions(missions, user_input="memory consolidation", domain="general")
    assert len(result) >= 1
    assert result[0].title == "Memory System"


def test_limit_respected():
    missions = [_make_mission(title=f"Mission {i}", domain="test") for i in range(10)]
    result = select_relevant_missions(missions, domain="test", limit=3)
    assert len(result) == 3


def test_empty_missions():
    result = select_relevant_missions([], user_input="test")
    assert len(result) == 0
