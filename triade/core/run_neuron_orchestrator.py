"""Orquestación de eventos y neuronas durante un run de Tríade Ω."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .background_neurons import candidates_from_system_debt
from .experimental_neuron_runtime import run_experimental_neurons
from .neuron_activity_store import NeuronActivityStore
from .neuron_formation_pipeline import form_candidates


def orchestrate_run_neurons(
    *,
    runner: Any,
    db_path: str | Path,
    input_packet: Any,
    signals: Any,
    memory: Any,
    crystal: Any,
    neuron_proposal: dict[str, Any] | None,
    post_run_learning: dict[str, Any],
    output_gate: dict[str, Any],
    output: Any,
    edge_usage: dict[str, Any],
    autopromotion_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Construye eventos de sistema y ejecuta neuronas experimentales.

    Mantiene al Runner como dueño de métodos legacy (_build_system_events y
    _filter_obsolete_edge_debt), pero separa la coordinación operativa.
    """
    system_events = runner._build_system_events(
        memory,
        crystal,
        neuron_proposal,
        post_run_learning,
        output_gate,
    )
    system_events = runner._filter_obsolete_edge_debt(system_events, edge_usage)

    experimental_neuron_activity = run_experimental_neurons(
        db_path=str(db_path),
        user_input=input_packet.user_input,
        context=input_packet.context or {},
        signals=signals,
        edge_usage=edge_usage,
        system_events=system_events,
    )

    neuron_activity_ids: list[int] = []
    if experimental_neuron_activity.get("active"):
        neuron_activity_ids = NeuronActivityStore(db_path=db_path).record_run_activity(
            input_packet.run_id,
            experimental_neuron_activity,
        )
        experimental_neuron_activity["db_activity_ids"] = neuron_activity_ids
        system_events.append({
            "type": "experimental_neuron_activity",
            "severity": "info",
            "status": "diagnostic_only",
            "message": f"{experimental_neuron_activity.get('count')} neurona(s) experimental(es) activadas en modo diagnóstico.",
            "action_required": "none",
            "payload": experimental_neuron_activity,
        })

    background_neuron_candidates = candidates_from_system_debt(
        pulse_summary=(input_packet.context or {}).get("system_pulse_summary"),
        output_gate=output_gate,
    )
    background_neuron_candidates = form_candidates(background_neuron_candidates)

    for candidate in background_neuron_candidates:
        system_events.append({
            "type": "background_neuron_candidate",
            "severity": candidate.get("severity", "medium"),
            "status": "requires_human_approval",
            "message": f"Neurona candidata propuesta: {candidate.get('display_name') or candidate.get('name')}",
            "action_required": "approve_or_reject_background_neuron",
            "payload": candidate,
        })

    if autopromotion_events:
        system_events.extend(autopromotion_events)

    output.memory_diff["post_run_learning"] = post_run_learning
    output.memory_diff["experimental_neuron_activity"] = experimental_neuron_activity
    output.memory_diff["neuron_activity_ids"] = neuron_activity_ids
    output.memory_diff["system_events"] = system_events
    output.memory_diff["background_neuron_candidates"] = background_neuron_candidates
    output.memory_diff["autopromotion_events"] = autopromotion_events
    output.memory_diff["output_gate"] = output_gate

    return {
        "system_events": system_events,
        "experimental_neuron_activity": experimental_neuron_activity,
        "neuron_activity_ids": neuron_activity_ids,
        "background_neuron_candidates": background_neuron_candidates,
    }
