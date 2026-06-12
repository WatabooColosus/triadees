"""Estado interno vivo del runtime local de Tríade."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now

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
