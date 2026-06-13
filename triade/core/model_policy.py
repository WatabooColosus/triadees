"""Política cognitiva de modelos locales para Tríade Ω."""

from __future__ import annotations

from typing import Any


CRITICAL_ROLES = {
    "neuron_nutrition",
    "learning_evaluation",
    "memory_diagnosis",
    "stable_consolidation",
    "semantic_embedding",
}

FALLBACK_RESPONSE_ROLES = {
    "chat_response",
    "hypothalamus_analysis",
    "central_reasoning",
}

ALL_ROLES = CRITICAL_ROLES | FALLBACK_RESPONSE_ROLES | {"federation_probe", "safety_review"}

DEFAULT_MODELS = {
    "chat_response": "qwen2.5:3b-instruct",
    "hypothalamus_analysis": "qwen2.5:3b-instruct",
    "central_reasoning": "qwen2.5:3b-instruct",
    "semantic_embedding": "nomic-embed-text:latest",
    "neuron_nutrition": "qwen2.5:3b-instruct",
    "learning_evaluation": "qwen2.5:3b-instruct",
    "memory_diagnosis": "qwen2.5:3b-instruct",
    "stable_consolidation": "qwen2.5:3b-instruct",
    "federation_probe": "qwen2.5:3b-instruct",
    "safety_review": "qwen2.5:3b-instruct",
}


def get_model_cognitive_policy(
    role: str,
    ollama_available: bool,
    requested_model: str | None = None,
    fallback_allowed: bool = True,
) -> dict[str, Any]:
    """Devuelve permisos explícitos para el rol cognitivo indicado."""

    clean_role = (role or "").strip().lower() or "central_reasoning"
    selected_model = (requested_model or DEFAULT_MODELS.get(clean_role) or DEFAULT_MODELS["central_reasoning"]).strip()
    model_required = clean_role in CRITICAL_ROLES

    allowed_actions: dict[str, bool] = {
        "allow_response": False,
        "allow_observation": True,
        "allow_fallback": False,
        "allow_learning_write": False,
        "allow_stable_memory_write": False,
        "allow_candidate_creation": False,
        "response_must_disclose_degraded_mode": False,
    }
    blocked_actions: list[str] = []
    degraded_reason: str | None = None

    if ollama_available:
        status = "full_local"
        allowed_actions.update(
            {
                "allow_response": True,
                "allow_fallback": False,
                "allow_learning_write": clean_role in CRITICAL_ROLES | {"central_reasoning"},
                "allow_stable_memory_write": clean_role in {"stable_consolidation"},
                "allow_candidate_creation": clean_role in CRITICAL_ROLES | {"central_reasoning", "hypothalamus_analysis"},
            }
        )
    elif clean_role in CRITICAL_ROLES:
        status = "degraded"
        degraded_reason = "Ollama no disponible; solo observación segura."
        allowed_actions.update(
            {
                "allow_response": False,
                "allow_fallback": bool(fallback_allowed),
                "allow_learning_write": False,
                "allow_stable_memory_write": False,
                "allow_candidate_creation": False,
            }
        )
        blocked_actions = [
            "deep_reasoning",
            "learning_write",
            "stable_memory_write",
            "candidate_creation",
            "semantic_consolidation",
        ]
        if clean_role == "neuron_nutrition":
            allowed_actions["allow_candidate_creation"] = False
            allowed_actions["candidate_creation_status"] = "candidate_requires_model_review"
    elif clean_role in FALLBACK_RESPONSE_ROLES:
        status = "fallback" if fallback_allowed else "degraded"
        degraded_reason = "Ollama no disponible; respuesta en fallback degradado."
        allowed_actions.update(
            {
                "allow_response": bool(fallback_allowed),
                "allow_fallback": bool(fallback_allowed),
                "response_must_disclose_degraded_mode": True,
            }
        )
        blocked_actions = ["learning_write", "stable_memory_write", "deep_reasoning"]
    else:
        status = "fallback" if fallback_allowed else "degraded"
        degraded_reason = "Ollama no disponible; capacidades cognitivas limitadas."
        allowed_actions.update({"allow_response": bool(fallback_allowed), "allow_fallback": bool(fallback_allowed)})
        blocked_actions = ["learning_write", "stable_memory_write"]

    return {
        "role": clean_role,
        "known_role": clean_role in ALL_ROLES,
        "ollama_available": bool(ollama_available),
        "model_required": model_required,
        "selected_model": selected_model,
        "status": status,
        "allowed_actions": allowed_actions,
        "blocked_actions": blocked_actions,
        "degraded_reason": degraded_reason,
        "truth": (
            "Ollama es el motor cognitivo local prioritario. "
            "El fallback permite responder u observar en modo degradado, "
            "pero no equivale a aprendizaje profundo ni memoria estable."
        ),
    }
