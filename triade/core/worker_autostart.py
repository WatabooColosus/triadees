"""Workers Always-On supervisor.

Mantiene los Living Workers activos sin saltarse Safety, Permission Governor
ni las protecciones internas del WorkerLoop.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.resource_governor import WORK_MODE_RANK, decide_work_mode
from triade.workers.background_service import WorkerBackgroundService


_WORKER_THREAD: threading.Thread | None = None
_WORKER_LOCK = threading.Lock()
_WORKER_STATE: dict[str, Any] = {
    "configured": False,
    "autostart": False,
    "watchdog": False,
    "active": False,
    "mode_configured": "observe_only",
    "mode_effective": "observe_only",
    "status": "disabled",
    "last_start_at": None,
    "last_error": None,
    "restart_attempts": 0,
    "degraded_by_governor": False,
    "degradation_reason": None,
}


def start_workers_if_configured(
    config: dict[str, Any],
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    """Arranca workers si runtime.workers_always_on/autostart lo permite."""

    if not bool(config.get("workers_always_on", True)):
        with _WORKER_LOCK:
            _WORKER_STATE.update({
                "configured": False,
                "autostart": bool(config.get("workers_autostart", False)),
                "watchdog": bool(config.get("workers_watchdog", False)),
                "active": False,
                "status": "disabled",
                "last_error": None,
            })
        _event("workers_disabled", {"reason": "workers_always_on=false"}, db_path=db_path)
        return build_workers_always_on_status()

    with _WORKER_LOCK:
        _WORKER_STATE.update({
            "configured": True,
            "autostart": bool(config.get("workers_autostart", True)),
            "watchdog": bool(config.get("workers_watchdog", True)),
            "mode_configured": str(config.get("worker_mode") or config.get("mode") or "full_local_guarded"),
        })

    if not bool(config.get("workers_autostart", True)):
        _event("workers_disabled", {"reason": "workers_autostart=false"}, db_path=db_path)
        return build_workers_always_on_status(db_path=db_path, runs_dir=runs_dir)

    return ensure_workers_alive(config, db_path=db_path, runs_dir=runs_dir)


def ensure_workers_alive(
    config: dict[str, Any],
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    """Inicia o reinicia workers si están configurados y no hay thread vivo."""

    global _WORKER_THREAD

    configured = bool(config.get("workers_always_on", True))
    autostart = bool(config.get("workers_autostart", True))
    watchdog = bool(config.get("workers_watchdog", True))
    mode_configured = str(config.get("worker_mode") or config.get("mode") or "full_local_guarded")
    mode_effective, degraded, reason = _decide_worker_mode(mode_configured)

    with _WORKER_LOCK:
        alive = bool(_WORKER_THREAD and _WORKER_THREAD.is_alive())
        _WORKER_STATE.update({
            "configured": configured,
            "autostart": autostart,
            "watchdog": watchdog,
            "mode_configured": mode_configured,
            "mode_effective": mode_effective,
            "degraded_by_governor": degraded,
            "degradation_reason": reason,
        })
        if not configured or not autostart:
            _WORKER_STATE.update({"active": False, "status": "disabled"})
            return dict(_WORKER_STATE)
        if alive:
            _WORKER_STATE.update({"active": True, "status": "running"})
            return build_workers_always_on_status(db_path=db_path, runs_dir=runs_dir)
        if _WORKER_STATE.get("last_start_at") and watchdog:
            _WORKER_STATE["restart_attempts"] = int(_WORKER_STATE.get("restart_attempts", 0) or 0) + 1
        _WORKER_STATE.update({"status": "starting", "last_error": None})

    def _run() -> None:
        try:
            service = WorkerBackgroundService(db_path=db_path, runs_dir=runs_dir)
            service.start(max_iterations=1_000_000, sleep_seconds=60.0, dry_run=False, task_timeout=30.0)
            with _WORKER_LOCK:
                if _WORKER_STATE.get("status") != "stop_requested":
                    _WORKER_STATE.update({"active": False, "status": "completed"})
        except Exception as exc:  # pragma: no cover - defensive path
            with _WORKER_LOCK:
                _WORKER_STATE.update({"active": False, "status": "failed", "last_error": str(exc)})
            _event("worker_autostart_failed", {"error": str(exc)}, db_path=db_path, severity="error")

    try:
        thread = threading.Thread(target=_run, name="triade-workers-always-on", daemon=True)
        thread.start()
        with _WORKER_LOCK:
            _WORKER_THREAD = thread
            _WORKER_STATE.update({
                "active": True,
                "status": "running",
                "last_start_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
            })
        _event("workers_started", {"mode_configured": mode_configured, "mode_effective": mode_effective}, db_path=db_path)
    except Exception as exc:
        with _WORKER_LOCK:
            _WORKER_STATE.update({"active": False, "status": "failed", "last_error": str(exc)})
        _event("workers_failed", {"error": str(exc)}, db_path=db_path, severity="error")

    return build_workers_always_on_status(db_path=db_path, runs_dir=runs_dir)


def stop_workers_always_on(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    with _WORKER_LOCK:
        _WORKER_STATE.update({"status": "stop_requested", "active": False})
    result = WorkerBackgroundService(db_path=db_path, runs_dir=runs_dir).stop()
    _event("workers_stop_requested", result, db_path=db_path)
    return build_workers_always_on_status(db_path=db_path, runs_dir=runs_dir)


def build_workers_always_on_status(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    service_status = WorkerBackgroundService(db_path=db_path, runs_dir=runs_dir).status()
    with _WORKER_LOCK:
        state = dict(_WORKER_STATE)
        thread_alive = bool(_WORKER_THREAD and _WORKER_THREAD.is_alive())
    active = bool(thread_alive or service_status.get("running"))
    state["active"] = active
    if state.get("configured") and active:
        state["status"] = "running"
    elif state.get("configured") and not active and state.get("status") not in ("starting", "failed", "stop_requested"):
        state["status"] = "inactive"
    state["thread_alive"] = thread_alive
    state["lock_file_active"] = bool(service_status.get("running"))
    state["service_status"] = service_status.get("status")
    state["stop_requested"] = bool(service_status.get("stop_requested"))
    return state


def _decide_worker_mode(mode_configured: str) -> tuple[str, bool, str | None]:
    import os
    force_mode = os.environ.get("TRIADE_FORCE_MODE", "").strip()
    if force_mode and force_mode in WORK_MODE_RANK:
        return force_mode, False, None
    try:
        from triade.core.ollama_blood import check_ollama_blood
        from triade.core.resource_probe import build_resource_probe
        from triade.core.always_on import load_always_on_config

        cfg = load_always_on_config()
        force_mode_cfg = str(cfg.get("force_mode", "")).strip()
        decision = decide_work_mode(build_resource_probe(), check_ollama_blood(), mode_configured, force_mode=force_mode_cfg if force_mode_cfg in WORK_MODE_RANK else None)
        effective = str(decision.get("effective_mode") or "observe_only")
        degraded = WORK_MODE_RANK.get(effective, 0) < WORK_MODE_RANK.get(mode_configured, 0)
        return effective, degraded, decision.get("reason") if degraded else None
    except Exception as exc:
        return "observe_only", True, f"worker_mode_decision_failed: {exc}"


def _event(event_type: str, payload: dict[str, Any], *, db_path: str | Path, severity: str = "info") -> None:
    try:
        from triade.core.internal_runtime import record_internal_runtime_event

        record_internal_runtime_event(event_type, "workers_always_on", payload, severity=severity)
    except Exception:
        pass
