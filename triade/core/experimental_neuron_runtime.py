"""Runtime seguro para neuronas experimentales y contribuidoras.

Una neurona puede observar, diagnosticar y contribuir al ciclo cognitivo
dentro de los límites de su estado. El nivel de contribución crece con
la confianza del sistema:

  candidate      → observe, diagnose
  experimental   → + propose_learning
  active_assistant → + influence_plan
  trusted_worker → + influence_response, write_experimental_memory
  stable         → + request_stable_promotion

Regla innegociable: ninguna neurona puede modificar identity_core.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from .contracts import (
    NEURON_STATUS_EFFECTS,
    NeuronContributionPacket,
)
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
    run_id: str = "",
) -> dict[str, Any]:
    """Ejecuta neuronas activas y produce NeuronContributionPackets."""
    registry = NeuronRegistry(db_path=db_path)
    neurons = [
        n
        for n in registry.list_neurons(limit=limit)
        if str(n.get("status"))
        in {
            "candidate",
            "experimental",
            "active_assistant",
            "trusted_worker",
            "stable",
        }
    ]

    activations: list[dict[str, Any]] = []
    contributions: list[NeuronContributionPacket] = []
    for neuron in neurons:
        match = should_activate(
            neuron,
            user_input=user_input,
            context=context,
            signals=signals,
            edge_usage=edge_usage,
        )
        if not match["active"]:
            continue

        contribution = build_contribution(
            neuron,
            run_id=run_id,
            user_input=user_input,
            context=context,
            signals=signals,
            edge_usage=edge_usage,
            system_events=system_events,
        )
        contributions.append(contribution)

        activations.append(
            {
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
                "contribution": contribution.to_dict(),
                "policy": f"neuron_status_{neuron.get('status')}_effects_limited",
            }
        )

    return {
        "active": bool(activations),
        "count": len(activations),
        "activations": activations,
        "contributions": [c.to_dict() for c in contributions],
        "contributions_count": len(contributions),
        "policy": {
            "can_modify_response": any(
                c.has_effect("influence_response") for c in contributions
            ),
            "can_modify_repo": False,
            "can_write_stable_memory": False,
            "can_execute_external_actions": False,
            "requires_human_review_for_promotion": True,
            "identity_core_protected": True,
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
    text = " ".join(
        [
            user_input or "",
            str(context.get("domain") or ""),
            str(context.get("active_neuron") or ""),
            str(getattr(signals, "intent", "") or ""),
            str(edge_usage.get("intent") or ""),
            " ".join(edge_usage.get("keywords") or []),
        ]
    ).lower()

    domain = str(neuron.get("domain") or "").lower()
    name = str(neuron.get("name") or "").lower()

    reasons: list[str] = []

    if domain == "federation_android_edge" and any(
        x in text for x in ["android", "apk", "nodo", "edge", "feder", "pulso"]
    ):
        reasons.append("domain:federation_android_edge matched input/context")
    elif domain == "system_governance" and any(
        x in text for x in ["estado", "verifica", "audita", "pulso", "neuron"]
    ):
        reasons.append("domain:system_governance matched input/context")
    elif domain == "model_runtime" and any(
        x in text for x in ["modelo", "ollama", "llm", "latencia"]
    ):
        reasons.append("domain:model_runtime matched input/context")
    elif domain == "memory_governance" and any(
        x in text for x in ["memoria", "semantic", "bodega"]
    ):
        reasons.append("domain:memory_governance matched input/context")

    # Lo que la neurona DECLARA saber atender. La tabla `neurons` tiene una
    # columna `triggers` desde el principio y 11 de 13 neuronas la rellenan;
    # nadie la leía. Sin esto, una neurona solo podía activarse si su dominio
    # estaba en la cadena de arriba —escrita a mano, con cuatro dominios— o si
    # un trozo de su nombre aparecía en el texto.
    #
    # El efecto medido era perverso: `neurona-llamo-santiago-wataboo-creador`
    # acumulaba 43 activaciones reales porque su nombre está hecho de palabras
    # de conversación, mientras `Neurona Visual` y `Neurona de Código y
    # Reparación` llevaban 0 en 35 pulsos. El routing premiaba a las neuronas
    # bautizadas con fragmentos de chat y mataba de hambre a las construidas
    # para trabajar. Y sin una sola activación no sintética, esas dos no pueden
    # alcanzar `stable` jamás.
    matched_trigger = _matching_trigger(neuron, text)
    if matched_trigger:
        reasons.append(f"trigger declarado coincide: {matched_trigger}")

    # El fallback por nombre se conserva —quitarlo dejaría sin activarse a las
    # neuronas que hoy funcionan así— pero se le aplica el mismo filtro de verbos
    # de intención. Medido: `neurona-quiero-informacion-sobre-banda` capturaba
    # «quiero aprender a dibujar en madera» porque «quiero» está en su nombre.
    # Un nombre que empieza con una muletilla no puede reclamar media
    # conversación.
    if name and any(
        part in text
        for part in name.replace("neurona-", "").split("-")
        if len(part) >= 5 and part not in _GENERIC_NAME_TOKENS
    ):
        reasons.append("name token matched input/context")

    return {
        "active": bool(reasons),
        "reasons": reasons,
    }


#: Trozos de nombre que no distinguen nada. Las neuronas creadas desde una frase
#: de chat se llaman como esa frase, así que su nombre arrastra muletillas.
_GENERIC_NAME_TOKENS = frozenset(
    [
        "quiero",
        "quisiera",
        "necesito",
        "podrias",
        "puedes",
        "informacion",
        "ayuda",
        "favor",
        "gracias",
        "saber",
        "sobre",
        "como",
        "cuando",
        "donde",
        "porque",
        "quien",
        "cual",
    ]
)

#: Triggers de ciclo de vida, no términos que un usuario escriba. Si se buscaran
#: en el texto activarían siempre o nunca, y la evidencia dejaría de significar
#: algo. Once de trece neuronas los declaran.
_LIFECYCLE_TRIGGERS = frozenset(
    {
        "every_session",
        "relevant_context",
        "candidate_state_review",
        "always",
        "on_demand",
    }
)


def _matching_trigger(neuron: dict[str, Any], text: str) -> str:
    """Primer trigger declarado que aparece en el texto, o cadena vacía.

    Tolera que `triggers` venga como lista ya decodificada, como JSON, o roto:
    un contrato mal formado no puede tumbar el ciclo cognitivo entero.
    """
    raw = neuron.get("triggers")
    values: list[Any]
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return ""
        values = parsed if isinstance(parsed, list) else []
    else:
        return ""

    for value in values:
        trigger = str(value).strip().lower()
        # `intent:build_or_update` y similares: se compara la parte útil.
        if ":" in trigger:
            trigger = trigger.split(":", 1)[1]
        if len(trigger) < 4 or trigger in _LIFECYCLE_TRIGGERS:
            continue
        if trigger in text:
            return trigger
    return ""


def build_contribution(
    neuron: dict[str, Any],
    *,
    run_id: str,
    user_input: str,
    context: dict[str, Any],
    signals: Any,
    edge_usage: dict[str, Any],
    system_events: list[dict[str, Any]],
) -> NeuronContributionPacket:
    """Construye un NeuronContributionPacket basado en el estado de la neurona."""
    neuron_status = str(neuron.get("status") or "candidate")
    allowed = list(NEURON_STATUS_EFFECTS.get(neuron_status, ("observe", "diagnose")))
    domain = str(neuron.get("domain") or "unknown")
    diagnosis = _build_diagnosis(domain, user_input, edge_usage, system_events)

    proposed_learning = ""
    if "propose_learning" in allowed:
        proposed_learning = _build_learning_proposal(domain, user_input, context)

    response_influence = ""
    if "influence_response" in allowed:
        response_influence = _build_response_influence(domain, user_input, context)

    evidence = [
        f"run:{run_id}",
        f"domain:{domain}",
        f"neuron_status:{neuron_status}",
    ]
    if edge_usage.get("used_edge"):
        evidence.append(f"edge:{edge_usage.get('node_id')}")

    risk: Literal["low", "medium", "high", "critical"] = "low"
    confidence = 0.50
    if neuron_status == "stable":
        confidence = 0.85
    elif neuron_status == "trusted_worker":
        confidence = 0.75
    elif neuron_status == "active_assistant":
        confidence = 0.65
    elif neuron_status == "experimental":
        confidence = 0.55

    return NeuronContributionPacket(
        run_id=run_id,
        neuron_id=str(neuron.get("id") or ""),
        neuron_name=str(neuron.get("name") or ""),
        neuron_status=neuron_status,
        neuron_domain=domain,
        activation_reason=f"domain:{domain} match",
        diagnosis=diagnosis,
        proposed_learning=proposed_learning,
        response_influence=response_influence,
        confidence=confidence,
        risk=risk,
        evidence_refs=evidence,
        allowed_effects=allowed,
    )


def _build_diagnosis(
    domain: str, user_input: str, edge_usage: dict, system_events: list
) -> str:
    parts = []
    if domain == "federation_android_edge":
        parts.append(f"Revisar coherencia edge_usage={edge_usage.get('accepted')}")
    elif domain == "system_governance":
        parts.append("Revisar salud del ciclo run y artifacts.")
    elif domain == "memory_governance":
        parts.append("Observar estado de memoria semántica.")
    elif domain == "model_runtime":
        parts.append("Observar rendimiento de modelos.")
    else:
        parts.append(f"Neurona observó dominio {domain}.")
    if len(system_events) > 3:
        parts.append(f"Alta actividad de sistema: {len(system_events)} eventos.")
    return ". ".join(parts)


def _build_learning_proposal(domain: str, user_input: str, context: dict) -> str:
    if domain == "system_governance":
        return "Evaluar si el patrón observado justifica un nuevo candidato de aprendizaje."
    if domain == "memory_governance":
        return "Revisar coherencia de memoria semántica para detectar gaps de conocimiento."
    return ""


def _build_response_influence(domain: str, user_input: str, context: dict) -> str:
    if domain == "system_governance":
        return "Considerar incluir diagnóstico neuronal en la respuesta al usuario."
    return ""
