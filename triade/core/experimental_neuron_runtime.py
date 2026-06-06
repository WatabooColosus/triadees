"""Runtime seguro para neuronas experimentales.

Una neurona experimental puede observar y diagnosticar dentro del run,
pero no puede ejecutar acciones, modificar memoria estable ni cambiar código.
"""

from __future__ import annotations

from typing import Any

from .neuron_registry import NeuronRegistry


def run_experimental_neurons(
    *,
    db_path: str,
    user_input: str,
    context: dict[str, Any],
    signals: Any,
    edge_usage: dict[str, Any],
    system_events: list[dict[str, Any]],
    limit: int = 20,
) -> dict[str, Any]:
    registry = NeuronRegistry(db_path=db_path)
    neurons = [
        n for n in registry.list_neurons(limit=limit)
        if str(n.get("status")) == "experimental"
    ]

    activations: list[dict[str, Any]] = []
    for neuron in neurons:
        match = should_activate(neuron, user_input=user_input, context=context, signals=signals, edge_usage=edge_usage)
        if not match["active"]:
            continue

        activations.append({
            "neuron_id": neuron.get("id"),
            "name": neuron.get("name"),
            "status": neuron.get("status"),
            "domain": neuron.get("domain"),
            "active": True,
            "match": match,
            "inputs_used": [
                "user_input",
                "signals.intent",
                "edge_usage",
                "system_events",
                "context",
            ],
            "output": build_diagnostic_output(neuron, user_input, context, signals, edge_usage, system_events),
            "policy": "experimental_neuron_no_external_actions_no_stable_memory_write",
        })

    return {
        "active": bool(activations),
        "count": len(activations),
        "activations": activations,
        "policy": {
            "can_modify_response": False,
            "can_modify_repo": False,
            "can_write_stable_memory": False,
            "can_execute_external_actions": False,
            "requires_human_review_for_promotion": True,
        },
    }


def should_activate(
    neuron: dict[str, Any],
    *,
    user_input: str,
    context: dict[str, Any],
    signals: Any,
    edge_usage: dict[str, Any],
) -> dict[str, Any]:
    text = " ".join([
        user_input or "",
        str(context.get("domain") or ""),
        str(context.get("active_neuron") or ""),
        str(getattr(signals, "intent", "") or ""),
        str(edge_usage.get("intent") or ""),
        " ".join(edge_usage.get("keywords") or []),
    ]).lower()

    domain = str(neuron.get("domain") or "").lower()
    name = str(neuron.get("name") or "").lower()

    reasons: list[str] = []

    if domain == "federation_android_edge" and any(x in text for x in ["android", "apk", "nodo", "edge", "feder", "pulso"]):
        reasons.append("domain:federation_android_edge matched input/context")
    elif domain == "system_governance" and any(x in text for x in ["estado", "verifica", "audita", "pulso", "neuron"]):
        reasons.append("domain:system_governance matched input/context")
    elif domain == "model_runtime" and any(x in text for x in ["modelo", "ollama", "llm", "latencia"]):
        reasons.append("domain:model_runtime matched input/context")
    elif domain == "memory_governance" and any(x in text for x in ["memoria", "semantic", "bodega"]):
        reasons.append("domain:memory_governance matched input/context")

    if name and any(part in text for part in name.replace("neurona-", "").split("-") if len(part) >= 5):
        reasons.append("name token matched input/context")

    return {
        "active": bool(reasons),
        "reasons": reasons,
    }


def build_diagnostic_output(
    neuron: dict[str, Any],
    user_input: str,
    context: dict[str, Any],
    signals: Any,
    edge_usage: dict[str, Any],
    system_events: list[dict[str, Any]],
) -> dict[str, Any]:
    domain = str(neuron.get("domain") or "unknown")
    diagnostics: list[str] = []
    test_plan: list[str] = []

    if domain == "federation_android_edge":
        diagnostics.append("Revisar coherencia entre edge_usage, pulso Android y eventos del run.")
        diagnostics.append(f"edge accepted={edge_usage.get('accepted')} node_id={edge_usage.get('node_id')}")
        test_plan.extend([
            "Verificar que edge_context.json exista en el run.",
            "Confirmar que llm_android_host del pulso sea real y no deuda legacy.",
            "Auditar que no se creen candidatas Android obsoletas.",
        ])
    elif domain == "system_governance":
        diagnostics.append("Revisar salud del ciclo run, artifacts e integridad.")
        test_plan.extend([
            "Validar presence de input/signals/plan/memory_diff/report/integrity.",
            "Confirmar que Safety no bloquee sin registrar causa.",
        ])
    else:
        diagnostics.append(f"Neurona experimental observó dominio {domain} sin acción externa.")
        test_plan.append("Registrar evidencia y esperar revisión humana antes de cualquier promoción.")

    return {
        "diagnosis": diagnostics,
        "test_plan": test_plan,
        "audit_summary": {
            "system_events_count": len(system_events or []),
            "signal_intent": getattr(signals, "intent", None),
            "edge_used": edge_usage.get("used_edge"),
            "edge_accepted": edge_usage.get("accepted"),
        },
        "human_review_request": False,
    }
