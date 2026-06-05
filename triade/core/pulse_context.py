"""Puente seguro entre el pulso vivo de la app y el contexto conversacional.

Este módulo mantiene el pulso vivo como contexto resumido para la Central sin
mezclar planes internos en la respuesta visible. Está separado de
`apps/single_port_app.py` para evitar tocar la UI grande en cada ajuste.
"""

from __future__ import annotations

from typing import Any, Callable


def as_dict(value: Any) -> dict[str, Any]:
    """Devuelve un dict seguro aunque el origen entregue strings/listas/None."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """Devuelve una lista segura aunque el origen entregue otro tipo."""
    return value if isinstance(value, list) else []


def summarize_pulse(pulse: dict[str, Any]) -> dict[str, Any]:
    """Reduce el pulso vivo a un contexto pequeño apto para el prompt.

    No expone estructuras completas ni secretos; solo estado, alertas y señales
    de capacidad necesarias para responder preguntas sobre pulso, nodos y
    aprendizaje en segundo plano.
    """
    pulse = as_dict(pulse)
    local = as_dict(pulse.get("local"))
    federation = as_dict(pulse.get("federation"))
    learning = as_dict(pulse.get("learning"))
    semantic = as_dict(pulse.get("semantic"))

    alerts = []
    for item in as_list(pulse.get("alerts"))[:8]:
        if not isinstance(item, dict):
            continue
        alerts.append(
            {
                "name": item.get("name"),
                "level": item.get("level"),
                "summary": item.get("summary"),
            }
        )

    nodes = []
    for item in as_list(federation.get("nodes"))[:8]:
        if not isinstance(item, dict):
            continue
        nodes.append(
            {
                "node_id": item.get("node_id"),
                "name": item.get("name"),
                "online": item.get("online"),
                "native_android": item.get("native_android"),
                "can_host_llm": item.get("can_host_llm"),
                "can_feed_local_models": item.get("can_feed_local_models"),
                "recommended_use": item.get("recommended_use"),
            }
        )

    return {
        "status": pulse.get("status"),
        "level": pulse.get("level"),
        "summary": pulse.get("summary"),
        "truth": pulse.get("truth"),
        "alerts": alerts,
        "local": {
            "ollama_ok": as_dict(local.get("ollama")).get("ok"),
            "docker_ok": as_dict(local.get("docker")).get("ok"),
            "hardware_tier": as_dict(local.get("hardware")).get("tier"),
            "missing_for_comfortable_models": local.get("missing_for_comfortable_models"),
        },
        "federation": {
            "node_count": federation.get("node_count"),
            "online_count": federation.get("online_count"),
            "android_native_online": federation.get("android_native_online"),
            "android_llm_hosts": federation.get("android_llm_hosts"),
            "nodes": nodes,
        },
        "semantic": {
            "candidate_count": semantic.get("candidate_count"),
            "stable_count": semantic.get("stable_count"),
            "quarantined_count": semantic.get("quarantined_count"),
        },
        "learning": {
            "post_run_learning_enabled": learning.get("post_run_learning_enabled"),
            "policy": learning.get("policy"),
        },
    }


def build_run_context_with_pulse(
    base_context: dict[str, Any] | None,
    build_system_pulse: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Construye contexto conversacional enriquecido con pulso vivo.

    Si el pulso falla, no rompe el chat: registra un resumen de error que la
    Central puede explicar al usuario sin traceback ni plan interno.
    """
    run_context = dict(base_context or {})
    try:
        pulse = build_system_pulse(sync_relay=False, intent="conversation", urgency="medium")
        run_context["system_pulse_summary"] = summarize_pulse(pulse)
    except Exception as exc:  # pragma: no cover - defensa runtime para UI local
        run_context["system_pulse_summary"] = {
            "status": "unknown",
            "level": "error",
            "summary": f"Pulso vivo no disponible: {exc}",
            "alerts": [
                {
                    "name": "pulse_context_error",
                    "level": "warning",
                    "summary": str(exc),
                }
            ],
        }
    return run_context
