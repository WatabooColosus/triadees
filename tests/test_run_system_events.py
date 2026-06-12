"""Pruebas de eventos de sistema derivados de runs."""

from __future__ import annotations

from types import SimpleNamespace

from triade.core.run_system_events import (
    build_system_events,
    filter_obsolete_edge_candidates,
    filter_obsolete_edge_debt,
)


def test_build_system_events_reports_semantic_learning_and_output_gate() -> None:
    memory = SimpleNamespace(semantic_recall={"governance": {"candidate_documents": 1, "quarantined_vector_matches": 2, "allowed_vector_matches": 3}})
    crystal = SimpleNamespace(temporal_status="degrading")

    events = build_system_events(
        memory=memory,
        crystal=crystal,
        neuron_proposal={"name": "neurona-test"},
        post_run_learning={"enabled": True, "candidate_id": "learn-1", "status": "candidate"},
        output_gate={"modified": True, "reason": "internal_leak_detected"},
    )

    event_types = {event["type"] for event in events}
    assert "semantic_candidates_pending" in event_types
    assert "semantic_quarantine_notice" in event_types
    assert "semantic_authorized_recall" in event_types
    assert "neuron_candidate_proposed" in event_types
    assert "post_run_learning_candidate" in event_types
    assert "crystal_temporal_alert" in event_types
    assert "output_gate_intervention" in event_types


def test_filter_obsolete_edge_debt_removes_android_host_debt_when_edge_was_used() -> None:
    events = [
        {"type": "background", "payload": {"evidence": {"name": "llm_android_host", "summary": "0 hosts LLM Android reales"}}},
        {"type": "other", "payload": {"name": "keep", "mission": "vigente"}},
    ]

    filtered = filter_obsolete_edge_debt(events, {"used_edge": True, "accepted": True, "node_id": "android"})

    assert [event["type"] for event in filtered] == ["other"]


def test_filter_obsolete_edge_candidates_removes_android_pairing_debt() -> None:
    candidates = [
        {"name": "federation", "mission": "Resolver ausencia de nodos Android nativos online"},
        {"name": "memory", "mission": "Mejorar memoria"},
    ]

    filtered = filter_obsolete_edge_candidates(candidates, {"used_edge": True, "accepted": True, "node_id": "android"})

    assert [candidate["name"] for candidate in filtered] == ["memory"]
