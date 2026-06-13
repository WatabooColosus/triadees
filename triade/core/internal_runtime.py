"""Estado interno vivo del runtime local de Tríade."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now

from triade.core.learning_journal import build_learning_journal
from triade.services.event_bus import build_context_from_events, publish_event
from triade.services.supervisor import InternalRuntimeSupervisor


_SUPERVISOR: InternalRuntimeSupervisor | None = None
_BACKGROUND_THREAD: threading.Thread | None = None
_LOCK = threading.Lock()
_LAST_CONTEXT_SNAPSHOT: dict[str, Any] = {}
_RUNTIME_EVENT_LOG: list[dict[str, Any]] = []

RUNTIME_CYCLE_EVENTS = {
    "runtime_cycle_start",
    "runtime_cycle_started",
    "runtime_cycle_complete",
    "runtime_cycle_completed",
}


def get_internal_runtime_supervisor(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> InternalRuntimeSupervisor:
    global _SUPERVISOR
    with _LOCK:
        if _SUPERVISOR is None or Path(db_path) != _SUPERVISOR.db_path or Path(runs_dir) != _SUPERVISOR.runs_dir:
            _SUPERVISOR = InternalRuntimeSupervisor(db_path=db_path, runs_dir=runs_dir)
        return _SUPERVISOR


def start_internal_runtime_background(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
    mode: str | None = None,
    interval_seconds: int | None = None,
    max_cycles: int | None = None,
) -> dict[str, Any]:
    global _BACKGROUND_THREAD
    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)
    with _LOCK:
        if _BACKGROUND_THREAD and _BACKGROUND_THREAD.is_alive():
            snap = supervisor.snapshot()
            return {
                "status": "already_running",
                "runtime_enabled": True,
                "mode": snap.get("mode"),
                "background_thread_alive": True,
                "interval_seconds": supervisor.interval_seconds,
                "started_at": snap.get("started_at"),
                "message": f"Runtime ya está activo en modo {snap.get('mode')}. No se creó duplicado.",
                "snapshot": snap,
            }
        supervisor.configure(mode=mode, enabled=True, interval_seconds=interval_seconds, max_cycles=max_cycles)
        supervisor.stop_file.unlink(missing_ok=True)
        thread = threading.Thread(
            target=supervisor.run_forever,
            kwargs={
                "interval_seconds": supervisor.interval_seconds,
                "max_cycles": supervisor.max_cycles,
                "mode": supervisor.mode,
            },
            daemon=True,
            name="triade-internal-runtime",
        )
        _BACKGROUND_THREAD = thread
        thread.start()
        snap = supervisor.snapshot()
        return {
            "status": "started",
            "runtime_enabled": True,
            "mode": snap.get("mode"),
            "background_thread_alive": True,
            "interval_seconds": supervisor.interval_seconds,
            "started_at": snap.get("started_at"),
            "message": f"Runtime iniciado en modo {snap.get('mode')} cada {supervisor.interval_seconds}s.",
            "snapshot": snap,
        }


def stop_internal_runtime_background(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    global _BACKGROUND_THREAD
    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)
    result = supervisor.stop()
    with _LOCK:
        thread = _BACKGROUND_THREAD
        if thread and thread.is_alive():
            thread.join(timeout=2)
        _BACKGROUND_THREAD = None
    from datetime import datetime, timezone
    return {
        "status": result.get("status", "stopped"),
        "runtime_enabled": False,
        "mode": supervisor.mode,
        "background_thread_alive": False,
        "stopped_at": datetime.now(timezone.utc).isoformat(),
        "message": "Runtime apagado.",
        "snapshot": supervisor.snapshot(),
    }


def get_internal_runtime_state(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)
    snapshot = supervisor.snapshot()
    return {
        "runtime_id": snapshot.get("runtime_id"),
        "started_at": snapshot.get("started_at"),
        "mode": snapshot.get("mode"),
        "enabled": snapshot.get("enabled"),
        "services": snapshot.get("services", {}),
        "counters": snapshot.get("counters", {}),
        "last_events": snapshot.get("last_events", []),
        "last_context_snapshot": snapshot.get("last_context_snapshot", {}),
        "safety_policy": snapshot.get("safety_policy", {}),
        "files": snapshot.get("files", {}),
    }


def build_internal_context_snapshot(
    limit: int = 50,
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)
    runtime_state = get_internal_runtime_state(db_path=db_path, runs_dir=runs_dir)
    events = build_context_from_events(limit=limit, db_path=db_path)
    snapshot = {
        "status": "ok",
        "runtime": runtime_state,
        "events": events,
        "generated_at": utc_now(),
    }
    global _LAST_CONTEXT_SNAPSHOT
    _LAST_CONTEXT_SNAPSHOT = snapshot
    return snapshot


def record_internal_runtime_event(
    event_type: str,
    source: str,
    payload: dict[str, Any] | None = None,
    severity: str = "info",
) -> dict[str, Any]:
    supervisor = get_internal_runtime_supervisor()
    event = publish_event(
        event_type,
        source,
        payload or {},
        severity=severity,
        db_path=supervisor.db_path,
        run_ref=supervisor.runtime_id,
    )
    supervisor.last_events.append(event)
    supervisor.last_events = supervisor.last_events[-20:]
    supervisor.counters["events"] += 1
    _RUNTIME_EVENT_LOG.append(event)
    return event


def runtime_background_status() -> dict[str, Any]:
    supervisor = get_internal_runtime_supervisor()
    return {
        "snapshot": supervisor.snapshot(),
        "background_thread_alive": bool(_BACKGROUND_THREAD and _BACKGROUND_THREAD.is_alive()),
        "last_context_snapshot": _LAST_CONTEXT_SNAPSHOT,
    }


def build_runtime_heartbeat(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
    since_hours: int = 24,
    limit: int = 50,
) -> dict[str, Any]:
    from triade.core.context_engine import build_living_context_for_chat
    from triade.core.error_bus import query_internal_errors
    from triade.core.ollama_blood import check_ollama_blood, ollama_blood_policy
    from triade.core.edge_observations import build_edge_context_health
    from triade.models.ollama_client import check_ollama_cognitive_health
    from triade.workers.background_service import WorkerBackgroundService
    from triade.core.always_on import build_always_on_status
    from triade.core.worker_autostart import build_workers_always_on_status

    runtime_state = get_internal_runtime_state(db_path=db_path, runs_dir=runs_dir)
    learning_journal = build_learning_journal(db_path=db_path, since_hours=since_hours, limit=limit)
    living_context = build_living_context_for_chat(
        user_input="pulso vivo",
        db_path=db_path,
        runs_dir=runs_dir,
        limit=limit,
    )
    worker_status = WorkerBackgroundService(db_path=db_path, runs_dir=runs_dir).status()
    workers_always_on_status = build_workers_always_on_status(db_path=db_path, runs_dir=runs_dir)
    recent_events = list_recent_runtime_events(limit=max(limit * 2, 100), db_path=db_path)
    last_cycle_at = _last_timestamp(recent_events, RUNTIME_CYCLE_EVENTS)
    latest_event = recent_events[0] if recent_events else None
    latest_error = _latest_noncritical_filtered_error(query_internal_errors(limit=20, db_path=db_path))
    edge_context_health = build_edge_context_health(since_hours=since_hours, limit=max(limit * 4, 200), db_path=db_path)
    active_missions = int((living_context.get("mission_context") or {}).get("active_missions", 0))
    ollama_blood = check_ollama_blood()
    blood_nutrition_policy = ollama_blood_policy("neuron_nutrition", ollama_blood)
    blood_evaluation_policy = ollama_blood_policy("learning_evaluation", ollama_blood)
    blood_stable_policy = ollama_blood_policy("stable_consolidation", ollama_blood)
    blood_semantic_policy = ollama_blood_policy("semantic_embedding", ollama_blood)
    ollama_health = check_ollama_cognitive_health()
    model_available = bool(ollama_blood.get("can_reason"))
    embedding_available = bool(ollama_blood.get("can_embed"))
    degraded_components: list[str] = []
    if blood_nutrition_policy["degraded"]:
        degraded_components.append("neuron_nutrition")
    if blood_evaluation_policy["degraded"]:
        degraded_components.append("learning_evaluation")
    if blood_stable_policy["degraded"]:
        degraded_components.append("stable_consolidation")
    if blood_semantic_policy["degraded"]:
        degraded_components.append("semantic_embedding")
    blocked_learning_actions = sorted(
        set(blood_nutrition_policy.get("blocked_actions", []))
        | set(blood_evaluation_policy.get("blocked_actions", []))
        | set(blood_stable_policy.get("blocked_actions", []))
        | set(blood_semantic_policy.get("blocked_actions", []))
    )
    fallback_message = "Tríade respira en fallback, pero no tiene sangre cognitiva activa."
    cycles_last_hour = _count_recent(recent_events, RUNTIME_CYCLE_EVENTS, hours=1)
    cycles_last_24h = _count_recent(recent_events, RUNTIME_CYCLE_EVENTS, hours=24)
    runtime_enabled = bool(runtime_state.get("enabled"))
    bg_alive = bool(_BACKGROUND_THREAD and _BACKGROUND_THREAD.is_alive())
    workers_active = bool(worker_status.get("running") or workers_always_on_status.get("active"))
    ollama_degraded = ollama_blood.get("status") == "degraded_no_ollama"

    always_on_status = build_always_on_status()
    always_on_enabled = always_on_status.get("enabled", False)
    always_on_state = always_on_status.get("status", "disabled")
    supervisor_enabled = bool(runtime_state.get("enabled"))
    has_recent_activity = cycles_last_hour > 0 or int(learning_journal.get("missions_executed", 0) or 0) > 0

    if has_recent_activity and not runtime_enabled and not bg_alive:
        runtime_activity_state = "recent_activity_supervisor_off"
    elif not has_recent_activity and not runtime_enabled and not bg_alive:
        runtime_activity_state = "idle_supervisor_off"
    elif always_on_enabled and not bg_alive:
        runtime_activity_state = "always_on_enabled_but_background_dead"
    elif always_on_enabled and bg_alive:
        runtime_activity_state = "active_background"
    elif ollama_degraded:
        runtime_activity_state = "degraded_no_ollama"
    elif bg_alive:
        runtime_activity_state = "always_on_enabled_background_running" if always_on_enabled else "active_background"
    else:
        runtime_activity_state = "idle_supervisor_off"

    configured_mode = str(always_on_status.get("configured_mode", "observe_only"))
    effective_mode = str(always_on_status.get("effective_mode", "observe_only"))
    degraded_by_governor = bool(always_on_status.get("degraded_by_governor") or workers_always_on_status.get("degraded_by_governor"))
    degradation_reason = always_on_status.get("degradation_reason") or workers_always_on_status.get("degradation_reason")

    if always_on_enabled and bg_alive and workers_active:
        truth = "ALWAYS-ON activo · Workers vivos · Tríade en proceso continuo"
    elif always_on_enabled and bg_alive and not workers_active:
        truth = "ALWAYS-ON activo · Workers inactivos: revisar autostart/watchdog"
    elif configured_mode == "full_local_guarded" and effective_mode != "full_local_guarded":
        truth = f"Autonomía full_local_guarded configurada · degradada a {effective_mode} por gobernador"
    elif always_on_enabled and bg_alive:
        truth = "ALWAYS-ON activo · Tríade en proceso continuo"
    elif always_on_enabled and not bg_alive:
        truth = "ALWAYS-ON configurado, pero background no está vivo"
    elif not always_on_enabled:
        truth = "ALWAYS-ON apagado · Runtime manual"
    elif ollama_degraded:
        truth = "Runtime degradado por falta de Ollama Blood"
    elif cycles_last_hour > 0:
        truth = "Runtime activo con ciclos recientes"
    else:
        truth = "Runtime activo sin ciclos recientes"
    if (
        configured_mode == "full_local_guarded"
        and effective_mode != "full_local_guarded"
        and "Autonomía full_local_guarded configurada" not in truth
    ):
        truth += f" · Autonomía full_local_guarded configurada · degradada a {effective_mode} por gobernador"

    heartbeat = {
        "status": "ok",
        "api_server_alive": True,
        "heartbeat_truth": truth,
        "background_thread_alive": bg_alive,
        "workers_active": workers_active,
        "runtime_enabled": runtime_enabled,
        "mode": runtime_state.get("mode"),
        "last_cycle_at": last_cycle_at,
        "cycles_last_hour": cycles_last_hour,
        "cycles_last_24h": max(cycles_last_24h, int(learning_journal.get("cycles_last_24h", 0) or 0)),
        "is_thinking_without_chat": bool(
            (learning_journal.get("cycles_last_24h", 0) or 0)
            or (learning_journal.get("missions_executed", 0) or 0)
            or (learning_journal.get("candidates_created", 0) or 0)
        ),
        "runtime_continuity_score": _heartbeat_continuity_score(
            runtime_enabled=bool(runtime_state.get("enabled")),
            cycles_last_hour=cycles_last_hour,
            active_workers=bool(worker_status.get("running")),
            active_missions=active_missions,
            learning_journal=learning_journal,
            latest_error=latest_error,
        ),
        "latest_action": (
            fallback_message
            if ollama_blood.get("status") == "degraded_no_ollama"
            else (latest_event or {}).get("event_type") or _first_event_type(runtime_state.get("last_events"))
        ),
        "latest_error": latest_error.get("message") or latest_error.get("error") or _first_event_message(runtime_state.get("last_events")),
        "active_workers": bool(worker_status.get("running")),
        "active_missions": active_missions,
        "ollama_health": ollama_health,
        "ollama_blood": ollama_blood,
        "edge_context_health": edge_context_health,
        "cognitive_blood_status": ollama_blood.get("status"),
        "blood_pressure_score": ollama_blood.get("blood_pressure_score", 0.0),
        "can_reason": bool(ollama_blood.get("can_reason")),
        "can_embed": bool(ollama_blood.get("can_embed")),
        "fallback_mode": bool(ollama_blood.get("fallback_mode")),
        "cognitive_model_status": "full_local" if model_available and embedding_available else ("degraded_no_ollama" if not ollama_blood.get("ollama_ok") else "partial_local"),
        "degraded_components": degraded_components,
        "blocked_learning_actions": blocked_learning_actions,
        "can_nourish_neurons": bool(ollama_blood.get("can_nourish_neurons")),
        "can_evaluate_learning": bool(ollama_blood.get("can_evaluate_learning")),
        "can_consolidate_stable_memory": bool(ollama_blood.get("can_consolidate_stable")),
        "can_consolidate_stable": bool(ollama_blood.get("can_consolidate_stable")),
        "model_policies": {
            "neuron_nutrition": blood_nutrition_policy,
            "learning_evaluation": blood_evaluation_policy,
            "stable_consolidation": blood_stable_policy,
            "semantic_embedding": blood_semantic_policy,
        },
        "learning_activity_summary": {
            "missions_executed": learning_journal.get("missions_executed", 0),
            "evidence_created": learning_journal.get("evidence_created", 0),
            "candidates_created": learning_journal.get("candidates_created", 0),
            "candidates_evaluated": learning_journal.get("candidates_evaluated", 0),
            "candidates_verified": learning_journal.get("candidates_verified", 0),
            "candidates_consolidated": learning_journal.get("candidates_consolidated", 0),
            "candidates_rejected": learning_journal.get("candidates_rejected", 0),
            "neurons_nourished": learning_journal.get("neurons_nourished", 0),
            "ollama_blood_message": fallback_message if ollama_blood.get("status") == "degraded_no_ollama" else "Sangre cognitiva activa o parcial.",
        },
        "neurons_nourished_last_24h": learning_journal.get("neurons_nourished", 0),
        "latest_contradiction": _latest_contradiction(living_context),
        "latest_learning_candidate": (learning_journal.get("latest_learning_candidates") or [{}])[0],
        "latest_rejection": (learning_journal.get("latest_rejections") or [{}])[0],
        "learning_journal": learning_journal,
        "living_context": living_context,
        "worker_status": worker_status,
        "workers_always_on": workers_always_on_status,
        "configured_autonomy": configured_mode,
        "effective_autonomy": effective_mode,
        "autonomy_degraded_by_governor": degraded_by_governor,
        "autonomy_degradation_reason": degradation_reason,
        "runtime_state": runtime_state,
        "runtime_events": recent_events[:20],
        "supervisor_enabled": supervisor_enabled,
        "has_recent_activity": has_recent_activity,
        "runtime_activity_state": runtime_activity_state,
        "always_on": {
            "enabled": always_on_enabled,
            "always_on_enabled": always_on_enabled,
            "configured_mode": always_on_status.get("configured_mode", "observe_only"),
            "effective_mode": always_on_status.get("effective_mode", "observe_only"),
            "interval_seconds": always_on_status.get("interval_seconds", 60),
            "config_source": always_on_status.get("config_source", "default"),
            "status": always_on_state,
            "background_thread_alive": bg_alive,
            "degraded_by_governor": bool(always_on_status.get("degraded_by_governor")),
            "degradation_reason": always_on_status.get("degradation_reason"),
            "last_start_at": always_on_status.get("last_start_at"),
            "last_start_result": always_on_status.get("last_start_result"),
            "last_self_test_status": always_on_status.get("last_self_test_status"),
            "error": always_on_status.get("error"),
            "self_test_on_start": always_on_status.get("self_test_on_start", True),
            "self_test_every_cycles": always_on_status.get("self_test_every_cycles", 5),
        },
        "always_on_enabled": always_on_enabled,
        "always_on_status": always_on_state,
        "always_on_background_thread_alive": bg_alive,
        "always_on_config_source": always_on_status.get("config_source", "default"),
        "always_on_effective_mode": always_on_status.get("effective_mode", "observe_only"),
        "always_on_detail": always_on_status,
        "self_test_last_status": getattr(get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir), "last_self_test_result", None),
    }
    return heartbeat


def list_recent_runtime_events(limit: int = 100, db_path: str | Path = "triade/memory/triade.db") -> list[dict[str, Any]]:
    return build_context_from_events(limit=limit, db_path=db_path).get("recent_events", [])


def _latest_noncritical_filtered_error(errors: list[dict[str, Any]]) -> dict[str, Any]:
    for err in errors or []:
        if not _is_expected_edge_parse_signal(err):
            return err
    return {}


def _is_expected_edge_parse_signal(err: dict[str, Any]) -> bool:
    text = " ".join(
        str(part or "")
        for part in (
            err.get("task_type"),
            err.get("message"),
            (err.get("payload") or {}).get("error_message"),
            ((err.get("payload") or {}).get("context") or {}).get("operation"),
        )
    ).lower()
    return (
        "edge_context.parse_model_output" in text
        and (
            "expecting value" in text
            or "jsondecodeerror" in text
            or "parse_model_json" in text
        )
    )


def _count_recent(events: list[dict[str, Any]], wanted: set[str], hours: int) -> int:
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


def _heartbeat_continuity_score(
    *,
    runtime_enabled: bool,
    cycles_last_hour: int,
    active_workers: bool,
    active_missions: int,
    learning_journal: dict[str, Any],
    latest_error: dict[str, Any],
) -> float:
    score = 0.0
    if runtime_enabled:
        score += 0.20
    if cycles_last_hour > 0:
        score += 0.20
    if active_workers:
        score += 0.15
    if active_missions > 0:
        score += 0.15
    if int(learning_journal.get("candidates_created", 0) or 0) > 0:
        score += 0.10
    if int(learning_journal.get("evidence_created", 0) or 0) > 0:
        score += 0.10
    if not latest_error or not latest_error.get("message"):
        score += 0.10
    return round(min(score, 1.0), 3)


def _latest_contradiction(living_context: dict[str, Any]) -> str | None:
    contradictions = (living_context.get("bodega_global_context") or {}).get("contradictions") or []
    if contradictions:
        return str(contradictions[0])
    bodega_summary = living_context.get("bodega_global_context") or {}
    if bodega_summary.get("contradictions"):
        return str(bodega_summary.get("contradictions")[0])
    return None


def _first_event_type(events: Any) -> str | None:
    if not isinstance(events, list) or not events:
        return None
    first = events[0] if isinstance(events[0], dict) else {}
    return str(first.get("event_type") or "") or None


def _first_event_message(events: Any) -> str | None:
    if not isinstance(events, list) or not events:
        return None
    first = events[0] if isinstance(events[0], dict) else {}
    return str(first.get("message") or "") or None
