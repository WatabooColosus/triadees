"""Reporte operativo compacto del runtime vivo de Tríade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.internal_runtime import get_internal_runtime_state
from triade.core.neuron_missions import NeuronMissionStore
from triade.core.stable_neuron_audit import audit_stable_neurons
from triade.learning.pipeline import LearningPipeline
from triade.models.hardware_profile import HardwareProfiler
from triade.models.ollama_client import OllamaClient
from triade.core.qualia import QUALIA
from triade.services.event_bus import list_recent_events
from triade.workers.background_service import WorkerBackgroundService


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
    cycles_last_hour = _count_recent(recent_events, {"runtime_cycle_start", "runtime_cycle_complete"}, hours=1)
    missions_executed_last_hour = _count_recent(recent_events, {"missions_executed"}, hours=1)
    candidates_created_last_hour = _count_recent(recent_events, {"learning_candidate_created"}, hours=1)
    last_cycle_at = _last_timestamp(recent_events, {"runtime_cycle_complete", "runtime_cycle_start"})
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
    return {
        "status": "ok",
        "is_thinking_without_chat": bool(cycles_last_hour or missions_executed_last_hour or candidates_created_last_hour),
        "runtime_enabled": bool(runtime.get("enabled")),
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
    }


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
