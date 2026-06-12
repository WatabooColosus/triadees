"""Orquestación de eventos y neuronas durante un run de Tríade Ω.

Ahora procesa NeuronContributionPackets del runtime neuronal:
- Los agrega a memory_diff y system_events
- Genera candidatos de aprendizaje cuando proposed_learning existe
- Pasa señales al QualiaBus sin consolidar memoria estable automáticamente
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .background_neurons import candidates_from_system_debt
from .contracts import NeuronContributionPacket
from .error_bus import record_internal_error
from .experimental_neuron_runtime import run_experimental_neurons
from .neuron_activity_store import NeuronActivityStore
from .neuron_formation_pipeline import form_candidates
from .neuron_mission_selector import select_relevant_missions
from .run_system_events import build_system_events, filter_obsolete_edge_debt


def orchestrate_run_neurons(
    *,
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
    """Construye eventos de sistema y ejecuta neuronas activas con contributions."""
    system_events = build_system_events(
        memory,
        crystal,
        neuron_proposal,
        post_run_learning,
        output_gate,
    )
    system_events = filter_obsolete_edge_debt(system_events, edge_usage)

    living_context = (input_packet.context or {}).get("living_context")
    mission_selection = select_relevant_missions(
        user_input=input_packet.user_input,
        domain=str((input_packet.context or {}).get("semantic_domain") or ""),
        memory_context=living_context if isinstance(living_context, dict) else input_packet.context or {},
        db_path=db_path,
        limit=5,
    )

    experimental_neuron_activity = run_experimental_neurons(
        db_path=str(db_path),
        user_input=input_packet.user_input,
        context=input_packet.context or {},
        signals=signals,
        edge_usage=edge_usage,
        system_events=system_events,
        run_id=input_packet.run_id,
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
            "status": "contributions_produced",
            "message": f"{experimental_neuron_activity.get('count')} neurona(s) activada(s), {experimental_neuron_activity.get('contributions_count', 0)} contribution(s).",
            "action_required": "none",
            "payload": experimental_neuron_activity,
        })

    contributions = _extract_contributions(experimental_neuron_activity)
    learning_candidates = _generate_learning_candidates_from_contributions(
        contributions, db_path=db_path, run_id=input_packet.run_id,
    )

    for lc in learning_candidates:
        system_events.append({
            "type": "neuron_learning_candidate",
            "severity": "info",
            "status": "auto_generated",
            "message": f"Candidato de aprendizaje generado desde contribución neuronal: {lc.get('candidate_id')}",
            "action_required": "evaluate_in_pipeline",
            "payload": lc,
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
            "status": "auto_approved",
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
    output.memory_diff["neuron_contributions"] = contributions
    output.memory_diff["neuron_learning_candidates"] = learning_candidates
    output.memory_diff["relevant_missions"] = mission_selection.get("selected", [])
    output.memory_diff["mission_selection_policy"] = mission_selection.get("policy", {})

    return {
        "system_events": system_events,
        "experimental_neuron_activity": experimental_neuron_activity,
        "neuron_activity_ids": neuron_activity_ids,
        "background_neuron_candidates": background_neuron_candidates,
        "neuron_contributions": contributions,
        "neuron_learning_candidates": learning_candidates,
        "relevant_missions": mission_selection.get("selected", []),
        "mission_selection_policy": mission_selection.get("policy", {}),
    }


def _extract_contributions(activity: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae las contributions del resultado del runtime neuronal."""
    contributions = activity.get("contributions") or []
    return [c for c in contributions if isinstance(c, dict)]


def _generate_learning_candidates_from_contributions(
    contributions: list[dict[str, Any]],
    *,
    db_path: str | Path,
    run_id: str,
) -> list[dict[str, Any]]:
    """Genera candidatos de aprendizaje cuando una contribution tiene proposed_learning."""
    from triade.learning.pipeline import LearningPipeline

    candidates = []
    try:
        pipe = LearningPipeline(db_path=db_path)
    except Exception as exc:
        record_internal_error(
            "run_neuron_orchestrator.learning_pipeline_init",
            exc,
            run_id=run_id,
            payload={"module": __name__, "function": "_generate_learning_candidates_from_contributions", "operation": "init_learning_pipeline"},
            db_path=db_path,
        )
        return candidates

    for contrib in contributions:
        proposed = str(contrib.get("proposed_learning") or "").strip()
        if not proposed:
            continue
        neuron_name = str(contrib.get("neuron_name") or "unknown")
        neuron_status = str(contrib.get("neuron_status") or "candidate")
        confidence = float(contrib.get("confidence") or 0.0)

        if confidence < 0.50:
            continue

        try:
            candidate = pipe.ingest(
                content=proposed,
                source_type="conversation",
                source_ref=f"neuron:{neuron_name}:run:{run_id}",
                title=f"Aprendizaje propuesto por {neuron_name}",
                domain=str(contrib.get("neuron_domain") or "general"),
                risk_level=str(contrib.get("risk") or "low"),
            )
            candidates.append({
                "candidate_id": candidate.get("candidate_id"),
                "source_neuron": neuron_name,
                "neuron_status": neuron_status,
                "confidence": confidence,
                "run_id": run_id,
            })
        except Exception as exc:
            record_internal_error(
                "run_neuron_orchestrator.learning_candidate_ingest",
                exc,
                run_id=run_id,
                payload={
                    "module": __name__,
                    "function": "_generate_learning_candidates_from_contributions",
                    "operation": "ingest_neuron_proposed_learning",
                    "neuron_name": neuron_name,
                },
                db_path=db_path,
            )

    return candidates
