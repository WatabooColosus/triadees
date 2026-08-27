"""Pruebas de eventos de sistema derivados de runs."""

from __future__ import annotations

from types import SimpleNamespace

from triade.core.run_system_events import (
    build_system_events,
    filter_obsolete_edge_candidates,
    filter_obsolete_edge_debt,
)


def test_build_system_events_reports_semantic_learning_and_output_gate() -> None:
    memory = SimpleNamespace(
        semantic_recall={
            "governance": {
                "candidate_documents": 1,
                "quarantined_vector_matches": 2,
                "allowed_vector_matches": 3,
            }
        }
    )
    crystal = SimpleNamespace(temporal_status="degrading")

    events = build_system_events(
        memory=memory,
        crystal=crystal,
        neuron_proposal={"name": "neurona-test"},
        post_run_learning={
            "enabled": True,
            "candidate_id": "learn-1",
            "status": "candidate",
        },
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


def test_filter_obsolete_edge_debt_removes_android_host_debt_when_edge_was_used() -> (
    None
):
    events = [
        {
            "type": "background",
            "payload": {
                "evidence": {
                    "name": "llm_android_host",
                    "summary": "0 hosts LLM Android reales",
                }
            },
        },
        {"type": "other", "payload": {"name": "keep", "mission": "vigente"}},
    ]

    filtered = filter_obsolete_edge_debt(
        events, {"used_edge": True, "accepted": True, "node_id": "android"}
    )

    assert [event["type"] for event in filtered] == ["other"]


def test_filter_obsolete_edge_candidates_removes_android_pairing_debt() -> None:
    candidates = [
        {
            "name": "federation",
            "mission": "Resolver ausencia de nodos Android nativos online",
        },
        {"name": "memory", "mission": "Mejorar memoria"},
    ]

    filtered = filter_obsolete_edge_candidates(
        candidates, {"used_edge": True, "accepted": True, "node_id": "android"}
    )

    assert [candidate["name"] for candidate in filtered] == ["memory"]


# ── §18.10: la procedencia del aprendizaje post-run nunca miente ────────────

from triade.core.run_system_events import _post_run_learning_event


def test_el_camino_delegado_no_afirma_haber_creado_candidato():
    """El bug literal: la UI mostraba «registrado como candidato: None».

    `delegated_to_governed_post_run_worker` es el camino vivo y **no produce
    `candidate_id` por diseño**: encola una tarea y el worker crea la fila
    después. La plantilla interpolaba una clave inexistente y afirmaba un
    registro que no había ocurrido.
    """
    evento = _post_run_learning_event(
        {
            "enabled": True,
            "mode": "delegated_to_governed_post_run_worker",
            "status": "scheduled",
        }
    )
    assert evento["provenance"] == "candidate_scheduled"
    assert evento["candidate_id"] is None
    assert "None" not in evento["message"]
    assert "todavía no existe candidato" in evento["message"]


def test_un_candidato_real_se_nombra_por_su_id():
    evento = _post_run_learning_event(
        {"enabled": True, "mode": "candidate_only", "candidate_id": "exp-abc123"}
    )
    assert evento["provenance"] == "candidate_created"
    assert evento["candidate_id"] == "exp-abc123"
    assert "exp-abc123" in evento["message"]


def test_cuando_no_se_crea_nada_se_dice_el_motivo():
    evento = _post_run_learning_event(
        {
            "enabled": True,
            "status": "skipped",
            "reason": "source_sin_aprendizaje:phase1-real-e2e",
        }
    )
    assert evento["provenance"] == "no_candidate_created"
    assert evento["candidate_id"] is None
    assert "source_sin_aprendizaje:phase1-real-e2e" in evento["message"]


def test_ningun_desenlace_imprime_none_en_el_mensaje():
    """La invariante que faltaba: `None` nunca es un id que enseñar."""
    for payload in (
        {"enabled": True, "mode": "delegated_to_governed_post_run_worker"},
        {"enabled": True, "mode": "candidate_only", "candidate_id": None},
        {"enabled": True, "status": "error", "reason": "enqueue_failed"},
        {"enabled": True},
    ):
        assert "None" not in _post_run_learning_event(payload)["message"], payload
