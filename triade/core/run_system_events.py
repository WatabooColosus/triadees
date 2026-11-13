"""Eventos de sistema y filtros de deuda derivados de un run."""

from __future__ import annotations

from typing import Any


def filter_obsolete_edge_candidates(
    candidates: list[dict], edge_usage: dict
) -> list[dict]:
    """Filtra neuronas candidatas obsoletas cuando Android edge ya fue probado."""
    if not (
        edge_usage.get("used_edge")
        and edge_usage.get("accepted")
        and edge_usage.get("node_id")
    ):
        return candidates

    blocked_fragments = (
        "nodos android",
        "hosts llm android",
        "llm_android_host",
        "android nativos online",
        "ausencia de nodos android",
        "preparaci",
        "emparejamiento",
    )

    filtered = []
    for candidate in candidates:
        haystack = " ".join(
            [
                str(candidate.get("name") or ""),
                str(candidate.get("display_name") or ""),
                str(candidate.get("source") or ""),
                str(candidate.get("mission") or ""),
                str((candidate.get("evidence") or {}).get("summary") or ""),
            ]
        ).lower()

        if any(fragment in haystack for fragment in blocked_fragments):
            continue
        filtered.append(candidate)

    return filtered


def filter_obsolete_edge_debt(
    system_events: list[dict], edge_usage: dict
) -> list[dict]:
    """Filtra deuda obsoleta de federación si el run ya probó edge Android LLM."""
    if not (
        edge_usage.get("used_edge")
        and edge_usage.get("accepted")
        and edge_usage.get("node_id")
    ):
        return system_events

    filtered = []
    obsolete_names = {"llm_android_host", "federation"}
    obsolete_texts = (
        "0 hosts LLM Android reales",
        "Sin nodos Android nativos online",
    )

    for event in system_events:
        payload = event.get("payload") or {}
        evidence = payload.get("evidence") or {}
        name = str(evidence.get("name") or payload.get("name") or "")
        summary = str(
            evidence.get("summary")
            or payload.get("mission")
            or event.get("message")
            or ""
        )

        if name in obsolete_names and any(text in summary for text in obsolete_texts):
            continue
        filtered.append(event)

    return filtered


def build_system_events(
    memory: Any,
    crystal: Any,
    neuron_proposal: Any | None,
    post_run_learning: dict[str, Any],
    output_gate: dict[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    semantic = getattr(memory, "semantic_recall", {}) or {}
    governance = semantic.get("governance", {}) if isinstance(semantic, dict) else {}
    pending_candidates = int(
        governance.get("candidate_matches", 0)
        or governance.get("candidate_documents", 0)
        or 0
    )
    quarantined = int(governance.get("quarantined_vector_matches", 0) or 0)
    allowed = int(governance.get("allowed_vector_matches", 0) or 0)

    if pending_candidates > 0:
        events.append(
            {
                "type": "semantic_candidates_pending",
                "severity": "info",
                "status": "auto_reviewed",
                "message": f"Hay {pending_candidates} memorias semánticas candidatas. Pueden informar como hipótesis, no como verdad estable.",
                "action_required": "none",
            }
        )
    if quarantined > 0:
        events.append(
            {
                "type": "semantic_quarantine_notice",
                "severity": "warning",
                "status": "blocked_as_fact",
                "message": f"Hay {quarantined} coincidencias semánticas en cuarentena. No se usarán como hechos.",
                "action_required": "review_quarantined_memory",
            }
        )
    if allowed > 0:
        events.append(
            {
                "type": "semantic_authorized_recall",
                "severity": "info",
                "status": "used_as_context",
                "message": f"Se encontraron {allowed} recuerdos semánticos autorizados para contexto.",
                "action_required": "none",
            }
        )
    if neuron_proposal is not None:
        events.append(
            {
                "type": "neuron_candidate_proposed",
                "severity": "important",
                "status": "auto_approved",
                "message": f"Se propuso la neurona candidata '{neuron_proposal.get('name')}'. Activación automática en proceso.",
                "action_required": "none",
                "payload": neuron_proposal,
            }
        )
    if post_run_learning.get("enabled"):
        events.append(_post_run_learning_event(post_run_learning))
    if getattr(crystal, "temporal_status", "stable") in {"critical", "degrading"}:
        events.append(
            {
                "type": "crystal_temporal_alert",
                "severity": "warning",
                "status": getattr(crystal, "temporal_status", "unknown"),
                "message": "El Cristal reporta degradación temporal. Conviene revisar continuidad y estabilidad antes de consolidar aprendizaje.",
                "action_required": "review_crystal_state",
            }
        )
    if output_gate.get("modified"):
        events.append(
            {
                "type": "output_gate_intervention",
                "severity": "warning",
                "status": output_gate.get("reason"),
                "message": "La salida intentó exponer proceso interno. OutputGate la corrigió antes de mostrarla al usuario.",
                "action_required": "review_output_gate",
            }
        )
    return events


def _post_run_learning_event(post_run_learning: dict[str, Any]) -> dict[str, Any]:
    """Dice qué pasó de verdad con el aprendizaje de este run.

    El mensaje anterior era «Aprendizaje post-run registrado como candidato:
    {candidate_id}», y se emitía con cualquier `enabled`. En el camino vivo
    —`delegated_to_governed_post_run_worker`— **no hay `candidate_id` por
    diseño**: se encola una tarea y el candidato lo crea el worker después. La
    plantilla interpolaba una clave inexistente y la UI acababa mostrando
    literalmente «registrado como candidato: None», afirmando un registro que
    no había ocurrido.

    Son tres desenlaces distintos y ninguno debe confundirse con otro:

    - ``candidate_created``   — existe fila y se da su id;
    - ``candidate_scheduled`` — hay tarea encolada, el id llegará después;
    - ``no_candidate_created``— no se creó nada, y se dice por qué.
    """
    modo = str(post_run_learning.get("mode") or "")
    candidate_id = post_run_learning.get("candidate_id")
    estado = str(post_run_learning.get("status") or "")

    if candidate_id:
        provenance = "candidate_created"
        message = (
            f"Aprendizaje post-run registrado como candidato {candidate_id}. "
            "Se evaluará y consolidará en segundo plano."
        )
    elif modo == "delegated_to_governed_post_run_worker" or estado == "scheduled":
        provenance = "candidate_scheduled"
        message = (
            "Aprendizaje post-run delegado al worker gobernado: hay tarea "
            "encolada y todavía no existe candidato. El id se asignará cuando "
            "la tarea se ejecute."
        )
    else:
        provenance = "no_candidate_created"
        motivo = str(
            post_run_learning.get("reason")
            or post_run_learning.get("error")
            or "sin motivo declarado"
        )
        message = f"No se creó candidato de aprendizaje para este run: {motivo}."

    return {
        "type": "post_run_learning_candidate",
        "severity": "important",
        "status": estado or "candidate_only",
        "provenance": provenance,
        "candidate_id": candidate_id or None,
        "message": message,
        "action_required": "none",
        "payload": post_run_learning,
    }
