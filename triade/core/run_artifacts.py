"""Utilidades de artifacts por run para Tríade Ω."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_run_artifacts(run_path: Path, artifacts: dict[str, Any]) -> list[str]:
    """Escribe artifacts JSON del run y devuelve nombres ordenados."""
    run_path.mkdir(parents=True, exist_ok=True)
    for filename, payload in artifacts.items():
        write_json(run_path / filename, payload)
    return sorted(artifacts.keys())


def write_run_integrity(
    *,
    run_path: Path,
    integrity: dict[str, Any],
    closed_text: str = "closed\n",
) -> None:
    """Escribe integrity.json y marca CLOSED."""
    run_path.mkdir(parents=True, exist_ok=True)
    write_json(run_path / "integrity.json", integrity)
    (run_path / "CLOSED").write_text(closed_text, encoding="utf-8")


def build_base_artifacts(
    *,
    input_packet: Any,
    signals: Any,
    edge_context: dict[str, Any],
    memory: Any,
    crystal: Any,
    plan_dict: dict[str, Any],
    safety: Any,
    output: Any,
    report: Any,
    system_events: list[dict[str, Any]],
    background_neuron_candidates: list[dict[str, Any]],
    experimental_neuron_activity: dict[str, Any],
    semantic_continuity: dict[str, Any],
    neuron_proposal: dict[str, Any] | None = None,
    post_run_learning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye el diccionario base de artifacts del runner."""
    artifacts: dict[str, Any] = {
        "input.json": input_packet.to_dict(),
        "signals.json": signals.to_dict(),
        "edge_context.json": edge_context,
        "memory.json": memory.to_dict(),
        "crystal.json": crystal.to_dict(),
        "plan.json": plan_dict,
        "plan_enriched.json": plan_dict,
        "safety.json": safety.to_dict(),
        "output.json": output.to_dict(),
        "memory_diff.json": output.memory_diff,
        "report.json": report.to_dict(),
        "system_events.json": system_events,
        "background_neuron_candidates.json": background_neuron_candidates,
        "experimental_neuron_activity.json": experimental_neuron_activity,
        "semantic_continuity.json": semantic_continuity,
    }

    if neuron_proposal is not None:
        artifacts["neuron_candidate.json"] = neuron_proposal

    if post_run_learning and post_run_learning.get("enabled"):
        artifacts["post_run_learning.json"] = post_run_learning

    return artifacts
