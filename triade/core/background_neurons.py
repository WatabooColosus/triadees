"""Neurona Formadora/Educadora · candidatos desde pulso vivo y deuda del sistema."""

from __future__ import annotations

import re
from typing import Any



def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+", "-", value.strip().lower()).strip("-")
    return cleaned[:80] or "deuda-sistema"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _candidate(name: str, mission: str, source: str, severity: str = "medium", evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Crea una candidata cruda.

    La formación real ocurre después en neuron_formation_pipeline.form_candidates(),
    donde operan N Creadora y N Formadora.
    """
    slug = _slug(name)
    return {
        "name": f"neurona-{slug}",
        "display_name": name,
        "status": "raw_candidate",
        "activation": "requires_formation_pipeline",
        "source": source,
        "severity": severity,
        "mission": mission,
        "evidence": evidence or {},
        "suggested_roles": ["monitor", "diagnose", "teach", "propose_fix", "verify"],
        "policy": "raw_candidate_must_pass_creator_trainer_pipeline",
    }


def candidates_from_system_debt(
    pulse_summary: dict[str, Any] | None = None,
    system_events: list[dict[str, Any]] | None = None,
    output_gate: dict[str, Any] | None = None,
    post_run_learning: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Genera neuronas candidatas cuando aparece deuda del sistema."""
    pulse = _as_dict(pulse_summary)
    events = [event for event in _as_list(system_events) if isinstance(event, dict)]
    output_gate = _as_dict(output_gate)
    post_run_learning = _as_dict(post_run_learning)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(candidate: dict[str, Any]) -> None:
        key = candidate.get("name") or candidate.get("display_name")
        if key in seen:
            return
        seen.add(str(key))
        candidates.append(candidate)

    pulse_status = str(pulse.get("status") or pulse.get("level") or "").lower()
    pulse_summary_text = str(pulse.get("summary") or "")
    if pulse_status in {"degraded", "critical", "warning", "error", "unknown"} or "degrad" in pulse_summary_text.lower():
        add(_candidate(
            "Guardiana de Pulso Vivo",
            "Vigilar degradación operativa, resumir causas, abrir tareas de recuperación y verificar estabilidad del sistema.",
            "pulse_summary",
            "high",
            {"pulse_status": pulse_status, "summary": pulse_summary_text},
        ))

    federation = _as_dict(pulse.get("federation"))
    if int(federation.get("android_native_online") or 0) <= 0:
        add(_candidate(
            "Arquitecta de Nodos Android",
            "Detectar ausencia de nodos Android nativos online y proponer pasos de emparejamiento, heartbeat y validación de runtime.",
            "pulse_federation",
            "medium",
            federation,
        ))
    if int(federation.get("android_llm_hosts") or 0) <= 0:
        add(_candidate(
            "Formadora de Hosts LLM Android",
            "Guiar la preparación de hosts LLM Android reales, validar recursos autorizados y reportar bloqueos de runtime.",
            "pulse_federation",
            "medium",
            federation,
        ))

    for alert in _as_list(pulse.get("alerts")):
        if not isinstance(alert, dict):
            continue
        name = str(alert.get("name") or "alerta-sistema")
        level = str(alert.get("level") or "medium")
        summary = str(alert.get("summary") or name)
        if "str" in summary and "get" in summary:
            add(_candidate(
                "Verificadora de Tipos Federados",
                "Detectar campos que llegan como string/lista cuando el sistema espera dict y proponer normalización defensiva.",
                "pulse_alert",
                "high",
                alert,
            ))
        else:
            add(_candidate(
                f"Educadora de Deuda · {name}",
                f"Estudiar y convertir la alerta del sistema en tarea verificable: {summary}",
                "pulse_alert",
                level,
                alert,
            ))

    for event in events:
        event_type = str(event.get("type") or "system_event")
        action = str(event.get("action_required") or "review")

        # Evitar recursión: una propuesta de neurona ya trae su propia revisión humana.
        # No debe generar otra neurona cuyo único propósito sea revisar que una neurona fue propuesta.
        if event_type in {"neuron_candidate_proposed", "background_neuron_candidate"}:
            continue

        if action and action != "none":
            add(_candidate(
                f"Formadora de Evento · {event_type}",
                f"Convertir el evento '{event_type}' en aprendizaje, prueba o tarea de reparación con aprobación humana.",
                "system_event",
                str(event.get("severity") or "medium"),
                event,
            ))

    if output_gate.get("modified"):
        add(_candidate(
            "Educadora de Salida Conversacional",
            "Aprender de intervenciones de OutputGate para mejorar prompts, evitar fugas internas y preservar identidad Tríade.",
            "output_gate",
            "medium",
            output_gate,
        ))

    if post_run_learning.get("enabled") or post_run_learning.get("candidate_id"):
        add(_candidate(
            "Educadora de Aprendizaje Post Run",
            "Revisar candidatos post-run, proponer evaluación, pruebas y criterios para posible consolidación posterior.",
            "post_run_learning",
            "medium",
            post_run_learning,
        ))

    return candidates
