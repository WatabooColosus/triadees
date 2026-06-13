"""Reporte operativo compacto del runtime vivo de Tríade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.internal_runtime import get_internal_runtime_state, RUNTIME_CYCLE_EVENTS
from triade.core.neuron_missions import NeuronMissionStore
from triade.core.stable_neuron_audit import audit_stable_neurons
from triade.learning.pipeline import LearningPipeline
from triade.models.hardware_profile import HardwareProfiler
from triade.models.ollama_client import OllamaClient
from triade.core.qualia import QUALIA
from triade.services.event_bus import list_recent_events
from triade.workers.background_service import WorkerBackgroundService
from triade.core.bodega_global_context import build_bodega_global_context


def build_living_report(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
    limit: int = 20,
) -> dict[str, Any]:
    db_path = Path(db_path)
    runs_dir = Path(runs_dir)
    runtime = get_internal_runtime_state(db_path=db_path, runs_dir=runs_dir)
    worker = WorkerBackgroundService(db_path=db_path, runs_dir=runs_dir)
    worker_status = worker.status()
    missions = NeuronMissionStore(db_path=db_path).list_missions(limit=200)
    learning = LearningPipeline(db_path=db_path)
    events = list_recent_events(limit=limit, db_path=db_path)
    qualia = QUALIA.snapshot(refresh_life=False)
    try:
        ollama = OllamaClient().health()
    except Exception as exc:
        ollama = {"ok": False, "error": str(exc)}
    try:
        stable_audit_raw = audit_stable_neurons(
            db_path=db_path,
            runs_dir=runs_dir,
            limit=200,
        )
        stable_audit = {
            "status": stable_audit_raw.get("status", "ok"),
            "total_stable_neurons": stable_audit_raw.get("total_stable_neurons", 0),
            "stable_with_enough_evidence": stable_audit_raw.get("stable_with_enough_evidence", 0),
            "stable_needs_review": stable_audit_raw.get("stable_needs_review", 0),
            "thresholds": stable_audit_raw.get("thresholds", {}),
            "policy": stable_audit_raw.get("policy", {}),
            "top_needs_review": [
                {
                    "name": n.get("name"),
                    "recommended_action": n.get("recommended_action"),
                    "blockers": n.get("blockers", []),
                    "evidence_source": n.get("evidence_source"),
                    "last_run_id": n.get("last_run_id"),
                }
                for n in (stable_audit_raw.get("neurons") or [])
                if n.get("recommended_action") != "keep_stable"
            ][:10],
        }
    except Exception as exc:
        stable_audit = {
            "status": "error",
            "error": str(exc),
            "total_stable_neurons": 0,
            "stable_with_enough_evidence": 0,
            "stable_needs_review": 0,
            "thresholds": {},
            "policy": {},
            "top_needs_review": [],
        }
    hardware = HardwareProfiler().detect()
    recent_events = list_recent_events(limit=200, db_path=db_path)
    cycles_last_hour = _count_recent(recent_events, RUNTIME_CYCLE_EVENTS, hours=1)
    missions_executed_last_hour = _count_recent(recent_events, {"missions_executed"}, hours=1)
    candidates_created_last_hour = _count_recent(recent_events, {"learning_candidate_created"}, hours=1)
    last_cycle_at = _last_timestamp(recent_events, RUNTIME_CYCLE_EVENTS)
    top_internal_events = [
        {
            "id": event.get("id"),
            "event_type": event.get("event_type"),
            "source": event.get("task_type") or event.get("message"),
            "status": event.get("status"),
            "message": event.get("message"),
            "created_at": event.get("created_at"),
        }
        for event in events[:10]
    ]
    try:
        bodega_global = build_bodega_global_context(
            user_input="estado interno",
            db_path=db_path,
            runs_dir=runs_dir,
            limit=10,
            semantic_recall_enabled=True,
        )
    except Exception:
        bodega_global = {
            "status": "error",
            "memory_confidence": "low",
            "memory_confidence_score": 0.0,
            "continuity_summary": "",
            "recommended_context_policy": "ask_or_operate_with_limited_memory",
            "contradictions": [],
            "semantic_recall": {},
            "recent_episodes": [],
            "semantic_engine_status": "unavailable",
        }
    bgc_mem_conf = bodega_global.get("memory_confidence", "low")
    bgc_needs_review = (bodega_global.get("stable_audit_summary") or {}).get("stable_needs_review", 0)
    continuity_score = _compute_runtime_continuity_score(
        runtime_enabled=bool(runtime.get("enabled")),
        cycles_last_hour=cycles_last_hour,
        missions_executed_last_hour=missions_executed_last_hour,
        candidates_created_last_hour=candidates_created_last_hour,
        memory_confidence=bgc_mem_conf,
        stable_needs_review=bgc_needs_review,
        qualia_state=qualia,
    )
    runtime_enabled = bool(runtime.get("enabled"))
    from triade.core.ollama_blood import check_ollama_blood
    _ollama_degraded = check_ollama_blood().get("status") == "degraded_no_ollama"
    if not runtime_enabled:
        truth = "Servidor activo · Runtime apagado"
        if _ollama_degraded:
            truth = "Servidor activo · Runtime apagado · Ollama no conectado"
    elif _ollama_degraded:
        truth = "Runtime degradado por falta de Ollama Blood"
    elif cycles_last_hour > 0:
        truth = "Runtime activo con ciclos recientes"
    else:
        truth = "Runtime activo sin ciclos recientes"

    return {
        "status": "ok",
        "api_server_alive": True,
        "heartbeat_truth": truth,
        "is_thinking_without_chat": bool(cycles_last_hour or missions_executed_last_hour or candidates_created_last_hour),
        "runtime_enabled": runtime_enabled,
        "runtime_mode": runtime.get("mode"),
        "runtime_id": runtime.get("runtime_id"),
        "last_cycle_at": last_cycle_at,
        "cycles_last_hour": cycles_last_hour,
        "missions_executed_last_hour": missions_executed_last_hour,
        "learning_candidates_created_last_hour": candidates_created_last_hour,
        "workers_active": bool(worker_status.get("running")),
        "models_available": ollama.get("models", []) if isinstance(ollama, dict) else [],
        "qualia_state": qualia,
        "top_internal_events": top_internal_events,
        "safety": {
            "identity_core_protected": True,
            "stable_memory_requires_learning_pipeline": True,
            "runtime_default_off": True,
            "worker_status": worker_status,
        },
        "summary": {
            "total_missions": len(missions),
            "learning_doctor": learning.doctor(),
            "hardware": hardware.to_dict(),
        },
        "stable_neuron_audit": stable_audit,
        "bodega_global_context_summary": {
            "status": bodega_global.get("status", "error"),
            "memory_confidence": bgc_mem_conf,
            "memory_confidence_score": bodega_global.get("memory_confidence_score", 0.0),
            "continuity_summary": bodega_global.get("continuity_summary", ""),
            "recommended_context_policy": bodega_global.get("recommended_context_policy", "ask_or_operate_with_limited_memory"),
            "contradictions_count": len(bodega_global.get("contradictions") or []),
            "semantic_matches_count": len((bodega_global.get("semantic_recall") or {}).get("semantic_matches", [])) if isinstance(bodega_global.get("semantic_recall"), dict) else 0,
            "recent_episodes_count": len(bodega_global.get("recent_episodes") or []),
            "stable_needs_review": bgc_needs_review,
            "semantic_engine_status": bodega_global.get("semantic_engine_status", "unavailable"),
        },
        "runtime_continuity_score": continuity_score,
    }


def _compute_runtime_continuity_score(
    *,
    runtime_enabled: bool,
    cycles_last_hour: int,
    missions_executed_last_hour: int,
    candidates_created_last_hour: int,
    memory_confidence: str,
    stable_needs_review: int,
    qualia_state: dict[str, Any],
) -> float:
    score = 0.0
    if runtime_enabled:
        score += 0.15
    if cycles_last_hour > 0:
        score += 0.15
    if missions_executed_last_hour > 0:
        score += 0.15
    if candidates_created_last_hour > 0:
        score += 0.15
    if memory_confidence == "high":
        score += 0.20
    elif memory_confidence == "medium":
        score += 0.10
    if stable_needs_review == 0:
        score += 0.10
    life = qualia_state.get("life") or qualia_state.get("qualia", {})
    if isinstance(life, dict) and life.get("status") == "ok":
        score += 0.10
    return min(score, 1.0)


def _count_recent(events: list[dict[str, Any]], wanted: set[str], hours: int = 1) -> int:
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    total = 0
    for event in events:
        if str(event.get("event_type") or "") not in wanted:
            continue
        created = str(event.get("created_at") or "")
        try:
            ts = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts >= cutoff:
            total += 1
    return total


def _last_timestamp(events: list[dict[str, Any]], wanted: set[str]) -> str | None:
    for event in events:
        if str(event.get("event_type") or "") in wanted:
            return str(event.get("created_at") or "")
    return None
