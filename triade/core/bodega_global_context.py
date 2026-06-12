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
from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.core.neuron_registry import NeuronRegistry

try:
    from triade.memory.semantic_search import SemanticSearchEngine
except ImportError:
    SemanticSearchEngine = None  # type: ignore[assignment,misc]

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

        bodega = Bodega(db_path=db_path)

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

        continuity_summary = _compute_continuity_summary(recent_episodes, semantic_matches)

        confidence_level, recommended_policy = _confidence_level(confidence_score)

        contradictions = _detect_contradictions(
            confidence_level=confidence_level,
            semantic_recall_info=semantic_recall_info,
            recent_episodes=recent_episodes,
            stable_audit_summary=stable_audit_summary,
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
            "stable_audit_summary": stable_audit_summary,
            "continuity_summary": continuity_summary,
            "contradictions": contradictions,
            "memory_confidence": confidence_level,
            "memory_confidence_score": confidence_score,
            "recommended_context_policy": recommended_policy,
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
            "stable_audit_summary": {"status": "unavailable"},
            "continuity_summary": "error al construir contexto",
            "contradictions": ["Error al construir Bodega Global Context."],
            "memory_confidence": "low",
            "memory_confidence_score": 0.0,
            "recommended_context_policy": "ask_or_operate_with_limited_memory",
            "truth": "La Bodega Global no pudo construirse. Operar con cautela.",
        }
