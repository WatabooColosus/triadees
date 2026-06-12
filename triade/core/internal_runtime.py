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
            return {"status": "already_running", "snapshot": supervisor.snapshot()}
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
        return {"status": "started", "snapshot": supervisor.snapshot()}


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
    return {**result, "snapshot": supervisor.snapshot()}


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
    from triade.workers.background_service import WorkerBackgroundService

    runtime_state = get_internal_runtime_state(db_path=db_path, runs_dir=runs_dir)
    learning_journal = build_learning_journal(db_path=db_path, since_hours=since_hours, limit=limit)
    living_context = build_living_context_for_chat(
        user_input="pulso vivo",
        db_path=db_path,
        runs_dir=runs_dir,
        limit=limit,
    )
    worker_status = WorkerBackgroundService(db_path=db_path, runs_dir=runs_dir).status()
    recent_events = list_recent_runtime_events(limit=max(limit * 2, 100), db_path=db_path)
    last_cycle_at = _last_timestamp(recent_events, {"runtime_cycle_start", "runtime_cycle_complete"})
    latest_event = recent_events[0] if recent_events else None
    latest_error = (query_internal_errors(limit=1, db_path=db_path) or [{}])[0]
    active_missions = int((living_context.get("mission_context") or {}).get("active_missions", 0))
    cycles_last_hour = _count_recent(recent_events, {"runtime_cycle_start", "runtime_cycle_complete"}, hours=1)
    cycles_last_24h = _count_recent(recent_events, {"runtime_cycle_start", "runtime_cycle_complete"}, hours=24)
    heartbeat = {
        "status": "ok",
        "runtime_enabled": bool(runtime_state.get("enabled")),
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
        "latest_action": (latest_event or {}).get("event_type") or _first_event_type(runtime_state.get("last_events")),
        "latest_error": latest_error.get("message") or latest_error.get("error") or _first_event_message(runtime_state.get("last_events")),
        "active_workers": bool(worker_status.get("running")),
        "active_missions": active_missions,
        "learning_activity_summary": {
            "missions_executed": learning_journal.get("missions_executed", 0),
            "evidence_created": learning_journal.get("evidence_created", 0),
            "candidates_created": learning_journal.get("candidates_created", 0),
            "candidates_evaluated": learning_journal.get("candidates_evaluated", 0),
            "candidates_verified": learning_journal.get("candidates_verified", 0),
            "candidates_consolidated": learning_journal.get("candidates_consolidated", 0),
            "candidates_rejected": learning_journal.get("candidates_rejected", 0),
            "neurons_nourished": learning_journal.get("neurons_nourished", 0),
        },
        "neurons_nourished_last_24h": learning_journal.get("neurons_nourished", 0),
        "latest_contradiction": _latest_contradiction(living_context),
        "latest_learning_candidate": (learning_journal.get("latest_learning_candidates") or [{}])[0],
        "latest_rejection": (learning_journal.get("latest_rejections") or [{}])[0],
        "learning_journal": learning_journal,
        "living_context": living_context,
        "worker_status": worker_status,
        "runtime_state": runtime_state,
    }
    return heartbeat


def list_recent_runtime_events(limit: int = 100, db_path: str | Path = "triade/memory/triade.db") -> list[dict[str, Any]]:
    return build_context_from_events(limit=limit, db_path=db_path).get("recent_events", [])


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
