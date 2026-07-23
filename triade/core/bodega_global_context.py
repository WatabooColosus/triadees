"""Bodega Global Context · Base global de contexto para toda la Tríade Ω.

Construye un contexto integral desde la Bodega de Almacenamiento para que
Central, Hipotálamo, Qualia y Workers accedan a identidad, episodios,
memoria semántica, neuronas, aprendizajes, seguridad y continuidad.

La Bodega deja de ser solo un contenedor pasivo de recuerdos y se convierte
en la base global obligatoria de contexto del sistema.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.bodega import Bodega
from triade.core.contracts import InputPacket
from triade.core.neuron_missions import NeuronMissionStore
from triade.core.ollama_blood import check_ollama_blood, ollama_blood_policy
from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.core.neuron_registry import NeuronRegistry

try:
    from triade.memory.semantic_store import SemanticMemoryStore
    from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
    from triade.memory.semantic_search import SemanticSearchEngine
    from triade.models.ollama_client import OllamaClient, check_ollama_cognitive_health
except ImportError:
    SemanticMemoryStore = None  # type: ignore[assignment,misc]
    SemanticEmbeddingEngine = None  # type: ignore[assignment,misc]
    SemanticSearchEngine = None  # type: ignore[assignment,misc]
    OllamaClient = None  # type: ignore[assignment,misc]
    check_ollama_cognitive_health = None  # type: ignore[assignment,misc]

try:
    from triade.core.stable_neuron_audit import audit_stable_neurons
except ImportError:
    audit_stable_neurons = None  # type: ignore[assignment,misc]


def _compute_memory_confidence(
    identity_matches: list[dict[str, Any]],
    semantic_matches: list[dict[str, Any]],
    recent_episodes: list[dict[str, Any]],
) -> float:
    """Calcula un score de confianza de memoria de 0.0 a 1.0.

    Señales: identidad (0.4), semántica (0.3), episodios recientes (0.3).
    """
    score = 0.0
    if identity_matches:
        score += 0.4
    if semantic_matches:
        score += 0.3
    if recent_episodes:
        score += 0.3
    return round(score, 2)


def _confidence_level(score: float) -> tuple[str, str]:
    """Retorna (memory_confidence, recommended_context_policy)."""
    if score >= 0.7:
        return "high", "use_full_context"
    if score >= 0.4:
        return "medium", "use_available_context"
    return "low", "ask_or_operate_with_limited_memory"


def _compute_continuity_summary(
    episodes: list[dict[str, Any]],
    semantic_matches: list[dict[str, Any]],
) -> str:
    """Genera un resumen textual de continuidad de memoria."""
    parts: list[str] = []
    if episodes:
        count = len(episodes)
        last_topic = ""
        first_episode = episodes[0] if episodes else {}
        if isinstance(first_episode, dict):
            last_topic = first_episode.get("summary", "")
        parts.append(f"{count} episodio(s) reciente(s)")
        if last_topic:
            parts.append(f"último tema: {last_topic[:80]}")
    if semantic_matches:
        parts.append(f"{len(semantic_matches)} coincidencia(s) semántica(s)")
    if not parts:
        return "sin continuidad de memoria previa"
    return "; ".join(parts)


def _group_project_context(semantic_matches: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Agrupa coincidencias semánticas por dominio."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for match in semantic_matches:
        if not isinstance(match, dict):
            continue
        domain = match.get("domain", "general")
        grouped.setdefault(domain, []).append(match)
    return grouped


def _detect_contradictions(
    *,
    confidence_level: str,
    semantic_recall_info: dict[str, Any],
    recent_episodes: list[dict[str, Any]],
    stable_audit_summary: dict[str, Any],
) -> list[str]:
    """Detecta contradicciones simples en el estado de memoria."""
    contradictions: list[str] = []
    if confidence_level == "low" and not recent_episodes:
        contradictions.append("Confianza baja y sin episodios recientes.")
    if confidence_level == "low" and semantic_recall_info.get("status") == "disabled":
        contradictions.append("Recuperación semántica desactivada con confianza baja.")
    needs_review = stable_audit_summary.get("stable_needs_review", 0)
    if needs_review > 0:
        contradictions.append(f"{needs_review} neurona(s) stable(s) requieren revisión de evidencia.")
    if semantic_recall_info.get("status") in ("unavailable", "disabled"):
        contradictions.append("Recuperación semántica no disponible o desactivada.")
    return contradictions


def _get_qualia_snapshot() -> dict[str, Any]:
    """Obtiene snapshot de Qualia si está disponible."""
    try:
        from triade.core.qualia import QUALIA
        return QUALIA.snapshot(refresh_life=False)
    except Exception:
        return {}


def _build_semantic_search_engine(
    db_path: str | Path,
    base_url: str | None = None,
    timeout: int = 60,
) -> Any:
    """Construye un SemanticSearchEngine completo con Ollama embeddings.

    Returns the engine if all dependencies are available, None otherwise.
    Does not raise.
    """
    if SemanticMemoryStore is None or SemanticEmbeddingEngine is None or SemanticSearchEngine is None or OllamaClient is None:
        return None
    try:
        store = SemanticMemoryStore(db_path=db_path)
        client = OllamaClient(base_url=base_url or "http://127.0.0.1:11434", timeout=timeout)
        embedding = SemanticEmbeddingEngine(store=store, client=client)
        engine = SemanticSearchEngine(store=store, client=client, embedding_engine=embedding)
        return engine
    except Exception:
        return None


def build_bodega_global_context(
    user_input: str,
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs",
    limit: int = 10,
    semantic_recall_enabled: bool = True,
) -> dict[str, Any]:
    """Construye el contexto global de la Bodega para toda la Tríade.

    Agrega identidad, episodios, memoria semántica, neuronas, aprendizajes,
    seguridad, qualia y continuidad en una sola llamada.

    Política:
    - No modifica identity_core.
    - No inventa recuerdos.
    - Todo nuevo aprendizaje entra como candidato.
    - Si no hay memoria suficiente, devuelve estado explícito.
    """
    try:
        db_path = Path(db_path)
        runs_dir = Path(runs_dir)

        semantic_engine_status = "disabled"
        semantic_engine_error: str | None = None
        semantic_degraded_reason: str | None = None
        embedding_model_used: str | None = None
        semantic_learning_allowed = False
        semantic_engine = None
        ollama_blood = check_ollama_blood()
        policy_bodega = ollama_blood_policy("bodega_diagnosis", ollama_blood)
        policy_semantic = ollama_blood_policy("semantic_embedding", ollama_blood)
        ollama_health = check_ollama_cognitive_health() if check_ollama_cognitive_health is not None else {"ok": False, "errors": ["ollama health unavailable"]}

        if semantic_recall_enabled:
            semantic_ready = bool(ollama_blood.get("can_embed"))
            if semantic_ready:
                semantic_engine = _build_semantic_search_engine(db_path)
            if semantic_engine is not None and semantic_ready:
                semantic_engine_status = "available"
                embedding_model_used = ollama_blood.get("embedding_model")
                semantic_learning_allowed = True
            else:
                semantic_engine_status = "unavailable"
                semantic_degraded_reason = "Ollama o modelo de embeddings no disponible."
                semantic_engine_error = "No se pudo construir SemanticSearchEngine (Ollama o dependencias no disponibles)."

        bodega = Bodega(db_path=db_path, semantic_search_engine=semantic_engine)

        packet = InputPacket(
            user_input=user_input or "contexto global",
            source="bodega_global_context",
            context={},
        )

        recall = bodega.recall(
            packet,
            semantic_recall_enabled=semantic_recall_enabled,
        )
        recall_dict = recall.to_dict()

        identity_context = recall_dict.get("identity_matches", [])
        semantic_recall_info = recall_dict.get("semantic_recall", {})
        semantic_matches = recall_dict.get("semantic_matches", [])
        episodic_matches = recall_dict.get("episodic_matches", [])
        confidence_score = recall_dict.get("confidence", 0.0)

        recent_episodes = bodega.list_recent_episodes(limit=limit)
        project_context = _group_project_context(semantic_matches)

        neuron_context: list[dict[str, Any]] = []
        try:
            registry = NeuronRegistry(db_path=db_path)
            all_neurons = registry.list_neurons(limit=limit)
            neuron_context = [
                {
                    "name": n.get("name"),
                    "status": n.get("status"),
                    "domain": n.get("domain"),
                    "mission": n.get("mission"),
                }
                for n in all_neurons
            ]
        except Exception:
            pass

        learning_context = {"candidates": 0, "evaluated": 0, "verified": 0}
        try:
            learning = LearningPipeline(db_path=db_path)
            candidates = learning.list_candidates(status="candidate", limit=limit)
            evaluated = learning.list_candidates(status="evaluated", limit=limit)
            verified = learning.list_candidates(status="verified", limit=limit)
            learning_context = {
                "candidates": len(candidates),
                "evaluated": len(evaluated),
                "verified": len(verified),
                "recent_candidates": candidates[:5],
            }
        except Exception:
            pass

        safety_context: dict[str, Any] = {
            "identity_core_protected": True,
            "stable_memory_requires_learning_pipeline": True,
            "candidate_is_not_stable_memory": True,
        }

        semantic_governance: dict[str, Any] = {}
        try:
            governance = SemanticMemoryGovernance(db_path=db_path)
            semantic_governance = governance.doctor()
        except Exception:
            semantic_governance = {"status": "unavailable"}

        stable_audit_summary: dict[str, Any] = {"status": "unavailable"}
        try:
            if audit_stable_neurons is not None:
                audit_result = audit_stable_neurons(
                    db_path=db_path,
                    runs_dir=runs_dir,
                    limit=limit,
                )
                stable_audit_summary = {
                    "status": audit_result.get("status", "ok"),
                    "total_stable_neurons": audit_result.get("total_stable_neurons", 0),
                    "stable_with_enough_evidence": audit_result.get("stable_with_enough_evidence", 0),
                    "stable_needs_review": audit_result.get("stable_needs_review", 0),
                    "policy": audit_result.get("policy", {}),
                }
                safety_context["stable_neuron_audit"] = stable_audit_summary
        except Exception:
            stable_audit_summary = {"status": "unavailable"}

        qualia_context = _get_qualia_snapshot()
        from triade.core.federated_global_edge import build_federated_global_edge_context
        federated_global_edge_context = build_federated_global_edge_context(db_path=db_path, limit=limit)

        continuity_summary = _compute_continuity_summary(recent_episodes, semantic_matches)
        if not ollama_blood.get("ollama_ok"):
            semantic_recall_mode = "degraded_no_ollama" if semantic_recall_enabled else "keyword_only"
        elif ollama_blood.get("can_embed"):
            semantic_recall_mode = "semantic_vector"
        elif ollama_blood.get("can_reason"):
            semantic_recall_mode = "model_reasoned"
        else:
            semantic_recall_mode = "keyword_only"

        confidence_level, recommended_policy = _confidence_level(confidence_score)

        contradictions = _detect_contradictions(
            confidence_level=confidence_level,
            semantic_recall_info=semantic_recall_info,
            recent_episodes=recent_episodes,
            stable_audit_summary=stable_audit_summary,
        )
        if not ollama_blood.get("ollama_ok") or not ollama_blood.get("can_embed"):
            from triade.services.event_bus import publish_event

            publish_event(
                "bodega_semantic_degraded_no_blood",
                "bodega_global_context",
                {
                    "blood_status": ollama_blood.get("status"),
                    "semantic_recall_mode": semantic_recall_mode,
                    "recommended_action": "Iniciar Ollama o instalar modelo de embeddings.",
                },
                severity="warning",
                db_path=db_path,
                run_ref="bodega-global-context",
            )

        return {
            "status": "ok",
            "mode": "bodega_global_context",
            "user_input": user_input,
            "identity_context": identity_context,
            "recent_episodes": recent_episodes,
            "semantic_recall": semantic_recall_info,
            "semantic_governance": semantic_governance,
            "project_context": project_context,
            "neuron_context": neuron_context,
            "learning_context": learning_context,
            "safety_context": safety_context,
            "qualia_context": qualia_context,
            "federated_global_edge_context": federated_global_edge_context,
            "stable_audit_summary": stable_audit_summary,
            "continuity_summary": continuity_summary,
            "contradictions": contradictions,
            "memory_confidence": confidence_level,
            "memory_confidence_score": confidence_score,
            "recommended_context_policy": recommended_policy,
            "semantic_engine_status": semantic_engine_status,
            "semantic_engine_error": semantic_engine_error,
            "semantic_degraded_reason": semantic_degraded_reason,
            "ollama_required_for_semantic_recall": True,
            "semantic_learning_allowed": semantic_learning_allowed,
            "embedding_model_used": embedding_model_used,
            "ollama_blood": ollama_blood,
            "semantic_recall_mode": semantic_recall_mode,
            "bodega_diagnosis_allowed": bool(policy_bodega.get("allowed")),
            "recommended_model_action": (
                "Iniciar Ollama o instalar modelo de embeddings."
                if not ollama_blood.get("ollama_ok") or not ollama_blood.get("can_embed")
                else "Ollama Blood activo para Bodega y memoria semántica."
            ),
            "recommended_action": (
                "Iniciar Ollama o instalar modelo de embeddings."
                if semantic_engine_status == "unavailable"
                else "Semantic recall disponible con embeddings locales."
            ),
            "recall_modes": {
                "keyword_recall": True,
                "semantic_vector_recall": semantic_engine_status == "available",
                "model_reasoned_recall": bool(ollama_blood.get("can_reason")),
            },
            "bodega_blood_policy": policy_bodega,
            "semantic_blood_policy": policy_semantic,
            "truth": (
                "La Bodega Global es la base obligatoria de contexto de Tríade. "
                "Candidate memory no es verdad estable. "
                "identity_core no se modifica desde este módulo. "
                "Todo recuerdo recuperado conserva trazabilidad de origen."
            ),
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "mode": "bodega_global_context",
            "user_input": user_input,
            "identity_context": [],
            "recent_episodes": [],
            "semantic_recall": {},
            "semantic_governance": {"status": "unavailable"},
            "project_context": {},
            "neuron_context": [],
            "learning_context": {"candidates": 0, "evaluated": 0, "verified": 0},
            "safety_context": {
                "identity_core_protected": True,
                "stable_memory_requires_learning_pipeline": True,
                "candidate_is_not_stable_memory": True,
            },
            "qualia_context": {},
            "federated_global_edge_context": {"status": "unavailable", "nodes": []},
            "stable_audit_summary": {"status": "unavailable"},
            "continuity_summary": "error al construir contexto",
            "contradictions": ["Error al construir Bodega Global Context."],
            "memory_confidence": "low",
            "memory_confidence_score": 0.0,
            "recommended_context_policy": "ask_or_operate_with_limited_memory",
            "semantic_engine_status": "unavailable",
            "semantic_engine_error": str(exc),
            "truth": "La Bodega Global no pudo construirse. Operar con cautela.",
        }
