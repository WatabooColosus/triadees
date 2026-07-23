"""Contexto vivo para que Central hable desde el estado interno y no solo desde el chat."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.bodega import Bodega
from triade.core.bodega_global_context import build_bodega_global_context
from triade.core.contracts import InputPacket
from triade.core.error_bus import query_internal_errors
from triade.core.internal_runtime import build_internal_context_snapshot, get_internal_runtime_state
from triade.core.neuron_identity_view import NeuronIdentityView
from triade.core.neuron_missions import NeuronMissionStore
from triade.core.qualia import QUALIA
from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient
from triade.qualia.bus import QualiaBus
from triade.workers.background_service import WorkerBackgroundService


def build_living_context_for_chat(
    user_input: str,
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
    limit: int = 10,
) -> dict[str, Any]:
    """Construye el contexto vivo interno para chat y API."""

    db_path = Path(db_path)
    runs_dir = Path(runs_dir)
    runtime_state = get_internal_runtime_state(db_path=db_path, runs_dir=runs_dir)
    internal_snapshot = build_internal_context_snapshot(limit=limit, db_path=db_path, runs_dir=runs_dir)
    worker_status = WorkerBackgroundService(db_path=db_path, runs_dir=runs_dir).status()
    bodega = Bodega(db_path=db_path)
    recall = bodega.recall(
        InputPacket(user_input=user_input or "estado interno", source="context_engine", context={}),
        semantic_recall_enabled=False,
    )
    episodes = bodega.list_recent_episodes(limit=limit)
    mission_store = NeuronMissionStore(db_path=db_path)
    missions = mission_store.list_missions(limit=limit)
    active_missions = [mission for mission in missions if mission.status in {"experimental", "stable"}]
    mission_cycles = {
        int(mission.id): mission_store.list_cycles(int(mission.id), limit=3)
        for mission in active_missions
        if mission.id is not None
    }
    mission_evidence = {
        int(mission.id): mission_store.list_evidence(int(mission.id), limit=3)
        for mission in active_missions
        if mission.id is not None
    }
    learning = LearningPipeline(db_path=db_path)
    candidates = learning.list_candidates(status="candidate", limit=limit)
    evaluated = learning.list_candidates(status="evaluated", limit=limit)
    verified = learning.list_candidates(status="verified", limit=limit)
    errors = query_internal_errors(limit=limit, db_path=db_path)
    qualia = QUALIA.snapshot(refresh_life=False)
    qualia_bus = QualiaBus(db_path=db_path).report(run_id=None)
    hardware = HardwareProfiler().detect()
    try:
        ollama_health = OllamaClient().health()
    except Exception as exc:
        ollama_health = {"ok": False, "error": str(exc)}
    router = ModelRouter(available_models=ollama_health.get("models", []) if isinstance(ollama_health, dict) else [], hardware=hardware)
    routes = router.route_many(intent="conversation", urgency="medium")

    try:
        bodega_global = build_bodega_global_context(
            user_input=user_input,
            db_path=db_path,
            runs_dir=runs_dir,
            limit=limit,
            semantic_recall_enabled=True,
        )
    except Exception as exc:
        bodega_global = {
            "status": "error",
            "error": str(exc),
            "memory_confidence": "low",
            "recommended_context_policy": "ask_or_operate_with_limited_memory",
        }

    memory_context = {
        "status": "ok",
        "recent_episodes": episodes,
        "semantic_recall": recall.to_dict() if hasattr(recall, "to_dict") else {},
        "semantic_governance": SemanticMemoryGovernance(db_path=db_path).doctor(),
        "learning_candidates_recent": candidates[:limit],
        "learning_candidates_evaluated": evaluated[:limit],
        "learning_candidates_verified": verified[:limit],
        "bodega_global_context": bodega_global,
        "memory_confidence": bodega_global.get("memory_confidence", "low"),
        "recommended_context_policy": bodega_global.get("recommended_context_policy", "ask_or_operate_with_limited_memory"),
    }
    mission_context = {
        "status": "ok",
        "total_missions": len(missions),
        "active_missions": len(active_missions),
        "missions": [mission.to_dict() for mission in active_missions[:limit]],
        "cycles": {
            str(mission_id): [cycle.to_dict() for cycle in cycles]
            for mission_id, cycles in mission_cycles.items()
        },
        "evidence": {
            str(mission_id): [item.to_dict() for item in items]
            for mission_id, items in mission_evidence.items()
        },
        "last_real_use": [
            {
                "mission_id": mission.get("id"),
                "title": mission.get("title"),
                "status": mission.get("status"),
                "latest_cycle": (mission_cycles.get(int(mission.get("id") or 0)) or [None])[0].to_dict() if mission.get("id") and mission_cycles.get(int(mission.get("id") or 0)) else None,
                "latest_evidence": (mission_evidence.get(int(mission.get("id") or 0)) or [None])[0].to_dict() if mission.get("id") and mission_evidence.get(int(mission.get("id") or 0)) else None,
            }
            for mission in [m.to_dict() for m in active_missions[:limit]]
        ],
    }
    qualia_context = {
        "status": qualia.get("status"),
        "state": qualia,
        "bus_report": qualia_bus,
    }
    internal_context = {
        "runtime": runtime_state,
        "life_pulse": runtime_state.get("services", {}).get("life_pulse", {}),
        "workers": worker_status,
        "missions": {
            "active_count": len(active_missions),
            "total_count": len(missions),
            "summary": mission_context,
        },
        "learning": {
            "doctor": learning.doctor(),
            "recent_candidates": candidates[:limit],
            "evaluated_candidates": evaluated[:limit],
            "verified_candidates": verified[:limit],
        },
        "qualia": qualia_context,
        "errors": errors,
        "models": {
            "hardware": hardware.to_dict(),
            "ollama": ollama_health,
            "routes": [route.to_dict() for route in routes] if isinstance(routes, list) else routes,
        },
        "federated_global_edge_context": bodega_global.get("federated_global_edge_context", {}),
    }
    trust_policy = {
        "identity_core_protected": True,
        "stable_memory_requires_learning_pipeline": True,
        "candidate_is_not_stable_memory": True,
        "runtime_default_off": True,
        "no_shell_by_default": True,
        "network_only_by_explicit_guarded_capability": True,
    }
    global_used = bodega_global.get("status") == "ok"
    return {
        "status": "ok",
        "chat_context": {
            "user_input": user_input,
            "query_mode": "living_context",
            "recent_memory_window": len(episodes),
            "bodega_global_used": global_used,
            "semantic_recall_enabled": True,
            "memory_confidence": bodega_global.get("memory_confidence", "low"),
            "recommended_context_policy": bodega_global.get("recommended_context_policy", "ask_or_operate_with_limited_memory"),
        },
        "internal_context": internal_context,
        "memory_context": memory_context,
        "bodega_global_context": bodega_global,
        "mission_context": mission_context,
        "qualia_context": qualia_context,
        "trust_policy": trust_policy,
        "runtime_state": runtime_state,
        "worker_status": worker_status,
        "errors": errors,
        "internal_snapshot": internal_snapshot,
    }
