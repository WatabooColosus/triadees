"""Adaptadores entre módulos reales de Tríade y QualiaBus."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import NeuronExperience
from .store import QualiaStore


def _risk_from_severity(value: str | None) -> str:
    text = str(value or "low").lower()
    if text in {"critical", "high", "medium", "low"}:
        return text
    if text in {"error", "warning"}:
        return "medium"
    return "low"


def build_run_experiences(
    *,
    run_id: str,
    post_run_learning: dict[str, Any] | None = None,
    neuron_orchestration: dict[str, Any] | None = None,
    experimental_neuron_activity: dict[str, Any] | None = None,
    background_neuron_candidates: list[dict[str, Any]] | None = None,
    semantic_continuity: dict[str, Any] | None = None,
    output_gate: dict[str, Any] | None = None,
) -> list[NeuronExperience]:
    experiences: list[NeuronExperience] = []
    post = post_run_learning or {}
    if post.get("candidate_id") or post.get("enabled"):
        experiences.append(NeuronExperience(
            run_id=run_id,
            neuron_id="post_run_learning",
            neuron_type="learning_pipeline",
            mission="Cerrar ciclo de aprendizaje post-run sin consolidar memoria estable.",
            source="post_run_learning",
            source_type="learning_candidate",
            observation=f"Post-run learning produjo estado {post.get('status') or 'candidate'}.",
            extracted_pattern=str(post.get("title") or post.get("candidate_id") or "candidato post-run"),
            proposed_learning=str(post.get("normalized_summary") or post.get("content") or ""),
            confidence=0.65 if post.get("candidate_id") else 0.45,
            risk=str(post.get("risk_level") or "low"),
            usefulness=0.7 if post.get("candidate_id") else 0.4,
            evidence_refs=[f"run:{run_id}", str(post.get("candidate_id") or "")],
        ))

    activity = experimental_neuron_activity or {}
    for activation in activity.get("activations") or []:
        if not isinstance(activation, dict):
            continue
        output = activation.get("output") if isinstance(activation.get("output"), dict) else {}
        diagnosis = output.get("diagnosis") if isinstance(output.get("diagnosis"), list) else []
        test_plan = output.get("test_plan") if isinstance(output.get("test_plan"), list) else []
        experiences.append(NeuronExperience(
            run_id=run_id,
            neuron_id=activation.get("neuron_id"),
            neuron_type="experimental_neuron",
            mission=str(activation.get("domain") or activation.get("name") or "observación experimental"),
            source=str(activation.get("name") or "experimental_neuron_activity"),
            source_type="experimental_neuron_activity",
            observation="; ".join(str(item) for item in diagnosis) or "Neurona experimental activada en modo diagnóstico.",
            extracted_pattern="; ".join(str(item) for item in test_plan),
            proposed_learning="",
            confidence=0.7,
            risk="low",
            usefulness=0.65,
            evidence_refs=[f"run:{run_id}", f"neuron_activity:{activation.get('neuron_id')}"] if activation.get("neuron_id") else [f"run:{run_id}"],
        ))

    for candidate in background_neuron_candidates or []:
        if not isinstance(candidate, dict):
            continue
        mission = str(candidate.get("mission") or candidate.get("display_name") or candidate.get("name") or "")
        experiences.append(NeuronExperience(
            run_id=run_id,
            neuron_id=str(candidate.get("name") or "background_candidate"),
            neuron_type="background_candidate",
            mission=mission,
            source=str(candidate.get("source") or "background_neuron_candidates"),
            source_type="background_neuron_candidate",
            observation=f"Candidata formada: {candidate.get('display_name') or candidate.get('name')}",
            extracted_pattern=str(candidate.get("policy") or "candidate_requires_review"),
            proposed_learning=mission,
            confidence=0.55,
            risk=_risk_from_severity(candidate.get("severity")),
            usefulness=0.6,
            evidence_refs=[f"run:{run_id}", str(candidate.get("name") or "")],
        ))

    sem = semantic_continuity or {}
    if sem.get("status") or sem.get("document_id"):
        experiences.append(NeuronExperience(
            run_id=run_id,
            neuron_id="semantic_continuity",
            neuron_type="memory_continuity",
            mission="Registrar continuidad semántica candidata sin promoción estable automática.",
            source="semantic_continuity",
            source_type="memory_continuity",
            observation=f"Continuidad semántica reportó {sem.get('status') or 'unknown'}.",
            extracted_pattern=str(sem.get("document_id") or sem.get("message") or "semantic_continuity"),
            proposed_learning="",
            confidence=0.6,
            risk="low",
            usefulness=0.55,
            evidence_refs=[f"run:{run_id}", str(sem.get("document_id") or "")],
        ))

    gate = output_gate or {}
    if gate.get("modified"):
        experiences.append(NeuronExperience(
            run_id=run_id,
            neuron_id="output_gate",
            neuron_type="safety_gate",
            mission="Aprender de sanitización de salida para reducir fugas internas.",
            source="output_gate",
            source_type="output_gate",
            observation=str(gate.get("reason") or "OutputGate modificó la respuesta."),
            extracted_pattern="La respuesta requirió sanitización antes de llegar al usuario.",
            proposed_learning="Mejorar prompts y salidas para evitar exposición de trazas internas o tono inadecuado.",
            confidence=0.65,
            risk="medium",
            usefulness=0.7,
            evidence_refs=[f"run:{run_id}", "artifact:output_gate.json"],
        ))

    for event in (neuron_orchestration or {}).get("system_events") or []:
        if not isinstance(event, dict):
            continue
        if str(event.get("action_required") or "none") == "none":
            continue
        experiences.append(NeuronExperience(
            run_id=run_id,
            neuron_id=str(event.get("type") or "system_event"),
            neuron_type="system_event",
            mission=str(event.get("action_required") or "review"),
            source="system_events",
            source_type="system_event",
            observation=str(event.get("message") or event.get("type") or "evento del sistema"),
            extracted_pattern=str(event.get("status") or "requires_review"),
            proposed_learning="",
            confidence=0.5,
            risk=_risk_from_severity(event.get("severity")),
            usefulness=0.5,
            evidence_refs=[f"run:{run_id}", f"system_event:{event.get('type') or 'unknown'}"],
        ))
    return experiences


def qualia_context_for_memory(db_path: str | Path, run_id: str | None = None, limit: int = 5) -> dict[str, Any]:
    try:
        store = QualiaStore(db_path=db_path)
        latest_state = store.latest_state(run_id=run_id)
        packets = store.list_central_packets(run_id=run_id, limit=limit, statuses={"hypothesis", "verified_context"})
        signals = store.list_signals(run_id=run_id, limit=limit)
        return {
            "status": "ok" if latest_state or packets or signals else "empty",
            "latest_qualia_state": latest_state,
            "central_knowledge_packets": packets,
            "relevant_signals": signals,
            "policy": "Qualia informa hipótesis/contexto; no es memoria estable salvo verificación/promoción explícita.",
        }
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc), "policy": "QualiaBus degradó sin romper recall."}
