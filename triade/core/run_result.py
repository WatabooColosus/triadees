"""Construcción del resultado final de un run de Tríade Ω."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_run_result(
    *,
    input_packet: Any,
    output: Any,
    system_events: list[dict[str, Any]],
    safety: Any,
    report: Any,
    semantic_state: dict[str, Any],
    temporal_state: dict[str, Any],
    hypothalamus_model_result: dict[str, Any],
    hypothalamus_quality: float,
    hypothalamus_event_id: int | None,
    central_quality: float,
    central_event_id: int | None,
    model_selection: dict[str, Any],
    neuron_proposal: dict[str, Any] | None,
    post_run_learning: dict[str, Any],
    background_neuron_candidates: list[dict[str, Any]],
    experimental_neuron_activity: dict[str, Any],
    output_gate: dict[str, Any],
    run_path: Path,
) -> dict[str, Any]:
    """Construye el payload público/operativo que devuelve TriadeRunner.run()."""
    return {
        "status": output.status or "ok",
        "run_id": input_packet.run_id,
        "response": output.response,
        "system_events": system_events,
        "safety": safety.to_dict(),
        "report": report.to_dict(),
        "memory_diff": output.memory_diff,
        "semantic_recall": semantic_state,
        "crystal_temporal_state": temporal_state,
        "models": {
            "hypothalamus": {
                **hypothalamus_model_result,
                "quality_score": hypothalamus_quality,
                "event_id": hypothalamus_event_id,
            },
            "central": {
                "provider": output.model_provider,
                "name": output.model_name,
                "ok": output.model_ok,
                "error": output.model_error,
                "quality_score": central_quality,
                "event_id": central_event_id,
            },
        },
        "model": {
            "provider": output.model_provider,
            "name": output.model_name,
            "ok": output.model_ok,
            "error": output.model_error,
        },
        "model_selection": model_selection,
        "neuron_proposal": neuron_proposal,
        "post_run_learning": post_run_learning,
        "background_neuron_candidates": background_neuron_candidates,
        "experimental_neuron_activity": experimental_neuron_activity,
        "output_gate": output_gate,
        "run_path": str(run_path),
    }
