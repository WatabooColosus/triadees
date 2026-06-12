"""Construcción de alcance contextual para comparación temporal del Cristal."""

from __future__ import annotations

from typing import Any

from .contracts import InputPacket


VALID_CONTEXT_SCOPES = {"source_intent", "session", "project", "neuron", "project_neuron"}


def build_comparison_basis(input_packet: InputPacket, intent: str) -> dict[str, Any]:
    context = input_packet.context or {}
    session_id = str(context.get("session_id", "")).strip() or None
    project_id = str(context.get("project_id", "")).strip() or None
    active_neuron = str(context.get("active_neuron", "")).strip() or None
    explicit_scope = str(context.get("context_scope", "")).strip() or None
    if explicit_scope and explicit_scope not in VALID_CONTEXT_SCOPES:
        explicit_scope = None

    if explicit_scope == "project_neuron" and project_id and active_neuron:
        scope = "project_neuron"
    elif explicit_scope == "neuron" and active_neuron:
        scope = "neuron"
    elif explicit_scope == "project" and project_id:
        scope = "project"
    elif explicit_scope == "session" and session_id:
        scope = "session"
    elif project_id and active_neuron:
        scope = "project_neuron"
    elif active_neuron:
        scope = "neuron"
    elif project_id:
        scope = "project"
    elif session_id:
        scope = "session"
    else:
        scope = "source_intent"

    fields: list[tuple[str, str]] = [("intent", intent)]
    if scope == "project_neuron":
        fields.extend([("project_id", project_id or ""), ("active_neuron", active_neuron or "")])
    elif scope == "neuron":
        fields.append(("active_neuron", active_neuron or ""))
    elif scope == "project":
        fields.append(("project_id", project_id or ""))
    elif scope == "session":
        fields.append(("session_id", session_id or ""))
    else:
        fields.append(("source", input_packet.source))

    context_key = scope + "|" + "|".join(f"{key}={value}" for key, value in fields)
    return {
        "context_scope": scope,
        "context_key": context_key,
        "source": input_packet.source,
        "intent": intent,
        "session_id": session_id,
        "project_id": project_id,
        "active_neuron": active_neuron,
    }
