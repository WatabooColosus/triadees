"""Ollama Blood · circulación cognitiva local de Tríade Ω."""

from __future__ import annotations

import time
from typing import Any

from triade.core.contracts import utc_now
from triade.models.ollama_client import OllamaClient


REASONING_PREFERENCES = [
    "qwen2.5:3b-instruct",
    "qwen3:4b",
    "llama3:latest",
    "qwen2.5-coder:7b",
    "qwen2.5-coder:3b",
]
EMBEDDING_PREFERENCES = ["nomic-embed-text:latest", "nomic-embed-text", "qwen3-embedding:0.6b"]
CODER_PREFERENCES = ["qwen2.5-coder:7b", "qwen2.5-coder:3b", "deepseek-coder-v2:16b", "qwen2.5-coder:1.5b-base"]


def check_ollama_blood(
    base_url: str | None = None,
    preferred_reasoning: str | None = None,
    preferred_embedding: str | None = None,
    preferred_coder: str | None = None,
) -> dict[str, Any]:
    """Diagnostica Ollama como sangre cognitiva local."""

    client = OllamaClient(base_url=base_url or "http://127.0.0.1:11434")
    started = time.perf_counter()
    health = client.health()
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    models = [str(model) for model in health.get("models", []) if model]
    ok = bool(health.get("ok"))

    reasoning_model = _select_model(models, preferred_reasoning, REASONING_PREFERENCES)
    embedding_model = _select_embedding(models, preferred_embedding)
    coder_model = _select_model(models, preferred_coder, CODER_PREFERENCES)

    can_reason = ok and bool(reasoning_model)
    can_embed = ok and bool(embedding_model)
    can_nourish = can_reason
    can_evaluate = can_reason
    can_consolidate = can_reason

    degraded_components: list[str] = []
    if not ok:
        status = "degraded_no_ollama"
        mode = "fallback_breathing"
        degraded_components = [
            "semantic_embedding",
            "bodega_diagnosis",
            "neuron_nutrition",
            "learning_evaluation",
            "stable_consolidation",
            "memory_contradiction_check",
            "worker_cycle",
        ]
        recommended_action = "Iniciar Ollama para activar sangre cognitiva local."
    else:
        if not can_reason:
            degraded_components.extend(["neuron_nutrition", "learning_evaluation", "stable_consolidation", "memory_contradiction_check", "worker_cycle"])
        if not can_embed:
            degraded_components.append("semantic_embedding")
        status = "ok" if not degraded_components else "degraded_missing_models"
        mode = "cognitive_blood_active" if status == "ok" else "partial_cognitive_blood"
        if not can_reason:
            recommended_action = "Instalar un modelo razonador compatible, por ejemplo qwen2.5:3b-instruct."
        elif not can_embed:
            recommended_action = "Instalar un modelo de embeddings compatible, por ejemplo nomic-embed-text."
        else:
            recommended_action = "Sangre cognitiva activa: Ollama alimenta razonamiento y embeddings locales."

    score = 0.0
    if ok:
        score += 0.25
    if reasoning_model:
        score += 0.25
    if embedding_model:
        score += 0.20
    if ok and latency_ms < 1500:
        score += 0.15
    if coder_model:
        score += 0.15

    return {
        "status": status,
        "ok": ok and status == "ok",
        "ollama_ok": ok,
        "mode": mode,
        "base_url": health.get("base_url", client.base_url),
        "models_available": models,
        "models": models,
        "reasoning_model": reasoning_model,
        "embedding_model": embedding_model,
        "coder_model": coder_model,
        "latency_ms": latency_ms,
        "can_reason": can_reason,
        "can_embed": can_embed,
        "can_nourish_neurons": can_nourish,
        "can_evaluate_learning": can_evaluate,
        "can_consolidate_stable": can_consolidate,
        "degraded_components": sorted(set(degraded_components)),
        "recommended_action": recommended_action,
        "blood_pressure_score": round(min(score, 1.0), 3),
        "checked_at": utc_now(),
        "errors": [str(health.get("error"))] if health.get("error") else [],
        "cognitive_blood_active": bool(ok and can_reason),
        "fallback_mode": not bool(ok and can_reason),
        "truth": "Fallback mantiene respiración mínima; Ollama Blood alimenta cognición local gobernada.",
    }


def ollama_blood_policy(role: str, blood_status: dict[str, Any]) -> dict[str, Any]:
    clean_role = (role or "chat_response").strip().lower()
    can_reason = bool(blood_status.get("can_reason"))
    can_embed = bool(blood_status.get("can_embed"))
    reasoning_model = blood_status.get("reasoning_model")
    embedding_model = blood_status.get("embedding_model")

    allowed = False
    degraded = False
    model_required = False
    model_used: str | None = None
    fallback_allowed = False
    stable_write_allowed = False
    allowed_actions: list[str] = ["observe", "record"]
    blocked_actions: list[str] = []
    reason = "Sangre cognitiva activa."

    if clean_role in {"chat_response", "central_reasoning", "hypothalamus_analysis"}:
        allowed = True
        fallback_allowed = True
        degraded = not can_reason
        model_used = reasoning_model
        allowed_actions.extend(["respond"])
        if degraded:
            reason = "Permitido en fallback: respiración mínima sin sangre cognitiva completa."
            blocked_actions.extend(["deep_reasoning", "learning_write", "stable_memory_write"])
    elif clean_role == "semantic_embedding":
        model_required = True
        allowed = can_embed
        model_used = embedding_model
        if allowed:
            allowed_actions.extend(["embed", "semantic_vector_recall"])
        else:
            degraded = True
            reason = "Requiere modelo de embeddings en Ollama Blood."
            blocked_actions.extend(["semantic_embedding", "semantic_learning"])
    elif clean_role == "bodega_diagnosis":
        allowed = True
        fallback_allowed = True
        degraded = not can_reason
        model_used = reasoning_model
        stable_write_allowed = False
        allowed_actions.extend(["keyword_recall", "diagnose_superficial" if degraded else "model_reasoned_diagnosis"])
        if degraded:
            reason = "Bodega puede diagnosticar de forma degradada, sin escritura stable."
            blocked_actions.extend(["stable_memory_write", "strong_semantic_diagnosis"])
    elif clean_role in {"neuron_nutrition", "learning_evaluation"}:
        model_required = True
        allowed = can_reason
        model_used = reasoning_model
        if allowed:
            allowed_actions.extend(["diagnose", "propose_learning"])
        else:
            degraded = True
            reason = "Requiere modelo razonador en Ollama Blood."
            blocked_actions.extend(["diagnose_deep", "propose_learning", "learning_write", "stable_memory_write"])
    elif clean_role == "memory_contradiction_check":
        model_required = True
        allowed = can_reason
        model_used = reasoning_model
        if allowed:
            allowed_actions.extend(["strong_contradiction_check"])
        else:
            degraded = True
            reason = "Requiere modelo razonador para diagnóstico fuerte de contradicciones."
            blocked_actions.append("strong_contradiction_check")
    elif clean_role == "stable_consolidation":
        model_required = True
        allowed = can_reason
        model_used = reasoning_model
        stable_write_allowed = can_reason
        if allowed:
            allowed_actions.extend(["review_gates", "stable_consolidation_if_external_gates_pass"])
        else:
            degraded = True
            reason = "Consolidación stable requiere Ollama Blood o aprobación humana explícita."
            blocked_actions.extend(["stable_memory_write", "auto_consolidation"])
    elif clean_role == "worker_cycle":
        allowed = True
        model_used = reasoning_model
        degraded = not can_reason
        allowed_actions.extend(["observe", "read_only"] if degraded else ["diagnose", "propose_learning"])
        if degraded:
            reason = "Worker cycle degradado: solo observe/read-only."
            blocked_actions.extend(["propose_learning", "stable_memory_write", "deep_diagnosis"])
    else:
        allowed = can_reason
        degraded = not can_reason
        model_required = True
        model_used = reasoning_model
        if degraded:
            reason = "Rol desconocido requiere sangre cognitiva para operar más allá de observación."
            blocked_actions.append("unknown_role_deep_action")

    return {
        "role": clean_role,
        "allowed": bool(allowed),
        "degraded": bool(degraded),
        "model_required": bool(model_required),
        "model_used": model_used,
        "fallback_allowed": bool(fallback_allowed),
        "stable_write_allowed": bool(stable_write_allowed),
        "allowed_actions": sorted(set(allowed_actions)),
        "blocked_actions": sorted(set(blocked_actions)),
        "reason": reason,
    }


def _select_model(models: list[str], preferred: str | None, defaults: list[str]) -> str | None:
    installed = set(models)
    if preferred and preferred in installed:
        return preferred
    for model in defaults:
        if model in installed:
            return model
    return None


def _select_embedding(models: list[str], preferred: str | None) -> str | None:
    selected = _select_model(models, preferred, EMBEDDING_PREFERENCES)
    if selected:
        return selected
    for model in models:
        clean = model.lower()
        if "embed" in clean or "embedding" in clean:
            return model
    return None
