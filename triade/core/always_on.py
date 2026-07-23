"""Always-On Runtime — Tríade se prueba a sí misma al arrancar.

Configuración persistente en triade.yml, sobrescribible por env vars.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.config import load_config
from triade.core.contracts import utc_now
from triade.core.internal_runtime import (
    get_internal_runtime_supervisor,
    record_internal_runtime_event,
    start_internal_runtime_background,
    stop_internal_runtime_background,
)
from triade.core.resource_governor import WORK_MODE_RANK, decide_work_mode
from triade.core.self_test_cycle import run_self_test_cycle

ENV_KEYS = {
    "enabled": "TRIADE_ALWAYS_ON",
    "mode": "TRIADE_ALWAYS_ON_MODE",
    "interval_seconds": "TRIADE_ALWAYS_ON_INTERVAL_SECONDS",
    "start_delay_seconds": "TRIADE_ALWAYS_ON_START_DELAY_SECONDS",
    "max_cycles": "TRIADE_ALWAYS_ON_MAX_CYCLES",
    "require_ollama": "TRIADE_ALWAYS_ON_REQUIRE_OLLAMA",
    "safe_only": "TRIADE_ALWAYS_ON_SAFE_ONLY",
    "self_test_on_start": "TRIADE_SELF_TEST_ON_START",
    "self_test_every_cycles": "TRIADE_SELF_TEST_EVERY_CYCLES",
    "workers_always_on": "TRIADE_WORKERS_ALWAYS_ON",
    "workers_autostart": "TRIADE_WORKERS_AUTOSTART",
    "workers_watchdog": "TRIADE_WORKERS_WATCHDOG",
    "worker_mode": "TRIADE_WORKER_MODE",
}

YML_DEFAULTS = {
    "enabled": False,
    "mode": "observe_only",
    "interval_seconds": 60,
    "start_delay_seconds": 3,
    "max_cycles": 0,
    "require_ollama": False,
    "safe_only": True,
    "self_test_on_start": True,
    "self_test_every_cycles": 5,
    "workers_always_on": True,
    "workers_autostart": True,
    "workers_watchdog": True,
    "worker_mode": "full_local_guarded",
}

_ALWAYS_ON_STATE: dict[str, Any] = {
    "enabled": False,
    "configured_mode": "observe_only",
    "effective_mode": "observe_only",
    "interval_seconds": 60,
    "max_cycles": 0,
    "config_source": "default",
    "background_thread_alive": False,
    "degraded_by_governor": False,
    "degradation_reason": None,
    "last_start_at": None,
    "last_cycle_at": None,
    "last_self_test_status": None,
    "last_start_result": None,
    "started_at": None,
    "status": "disabled",
    "error": None,
}


def _str_to_bool(v: Any) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def load_always_on_config(yml_path: str | Path = "triade.yml") -> dict[str, Any]:
    """Carga configuración en orden: defaults → triade.yml → env vars."""
    cfg = dict(YML_DEFAULTS)
    cfg["_config_source"] = "default"

    # ── triade.yml ──
    try:
        yml = load_config(yml_path)
        rtc: dict = yml.get("runtime") or {}
        if rtc:
            for key in YML_DEFAULTS:
                if key in rtc:
                    cfg[key] = rtc[key]
            if "always_on" in rtc:
                cfg["enabled"] = bool(rtc["always_on"])
            cfg["_config_source"] = "triade.yml"
    except Exception:
        pass

    # ── env vars ──
    env_hit = False
    for key, env_name in ENV_KEYS.items():
        raw = os.environ.get(env_name)
        if raw is not None:
            env_hit = True
            if key in (
                "enabled",
                "require_ollama",
                "safe_only",
                "self_test_on_start",
                "workers_always_on",
                "workers_autostart",
                "workers_watchdog",
            ):
                cfg[key] = _str_to_bool(raw)
            elif key in ("interval_seconds", "start_delay_seconds", "max_cycles", "self_test_every_cycles"):
                try:
                    cfg[key] = int(raw)
                except ValueError:
                    pass
            else:
                cfg[key] = raw.strip()

    if env_hit:
        cfg["_config_source"] = "env"

    cfg["_max_cycles_param"] = None if cfg["max_cycles"] == 0 else cfg["max_cycles"]
    return cfg


def should_start_always_on(yml_path: str | Path = "triade.yml") -> bool:
    cfg = load_always_on_config(yml_path)
    return bool(cfg.get("enabled", False))


def _background_thread_alive() -> bool:
    from triade.core import internal_runtime

    thread = getattr(internal_runtime, "_BACKGROUND_THREAD", None)
    return bool(thread and thread.is_alive())


def build_always_on_status() -> dict[str, Any]:
    global _ALWAYS_ON_STATE
    bg_alive = _background_thread_alive()
    _ALWAYS_ON_STATE["background_thread_alive"] = bg_alive
    if _ALWAYS_ON_STATE["enabled"] and not bg_alive:
        _ALWAYS_ON_STATE["status"] = "background_dead"
    elif _ALWAYS_ON_STATE["enabled"] and bg_alive:
        _ALWAYS_ON_STATE["status"] = "running"
    else:
        _ALWAYS_ON_STATE["status"] = "disabled"
    state = dict(_ALWAYS_ON_STATE)
    state["always_on_enabled"] = bool(state.get("enabled", False))
    return state


def start_always_on_if_enabled(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
    yml_path: str | Path = "triade.yml",
) -> dict[str, Any]:
    global _ALWAYS_ON_STATE

    cfg = load_always_on_config(yml_path)

    if not cfg.get("enabled", False):
        _ALWAYS_ON_STATE["enabled"] = False
        _ALWAYS_ON_STATE["status"] = "disabled"
        _ALWAYS_ON_STATE["error"] = None
        return {"status": "disabled", "message": "ALWAYS-ON no está habilitado.", "config_source": cfg["_config_source"]}

    bg_alive = _background_thread_alive()
    if bg_alive:
        _ALWAYS_ON_STATE["background_thread_alive"] = True
        _ALWAYS_ON_STATE["status"] = "running"
        return {"status": "already_running", "background_thread_alive": True, "config_source": cfg["_config_source"]}

    # ── Store config ──
    _ALWAYS_ON_STATE["enabled"] = True
    _ALWAYS_ON_STATE["configured_mode"] = str(cfg.get("mode", "observe_only"))
    _ALWAYS_ON_STATE["interval_seconds"] = int(cfg.get("interval_seconds", 60))
    _ALWAYS_ON_STATE["max_cycles"] = int(cfg.get("max_cycles", 0))
    _ALWAYS_ON_STATE["config_source"] = cfg.get("_config_source", "default")
    _ALWAYS_ON_STATE["status"] = "starting"

    # ── Delay ──
    delay = max(0, int(cfg.get("start_delay_seconds", 3)))
    if delay > 0:
        time.sleep(delay)

    # ── Preflight ──
    preflight_errors: list[str] = []

    try:
        from triade.core.ollama_blood import check_ollama_blood
        blood = check_ollama_blood()
        ollama_ok = bool(blood.get("ollama_ok"))
    except Exception as exc:
        blood = {}
        ollama_ok = False
        preflight_errors.append(f"ollama_blood_check_failed: {exc}")

    try:
        from triade.core.resource_probe import build_resource_probe
        probe = build_resource_probe()
    except Exception as exc:
        probe = {}
        preflight_errors.append(f"resource_probe_failed: {exc}")

    try:
        supervisor = get_internal_runtime_supervisor(db_path=db_path, runs_dir=runs_dir)
        supervisor.snapshot()
    except Exception as exc:
        preflight_errors.append(f"db_or_supervisor_failed: {exc}")

    # ── Decide effective mode ──
    requested_mode = str(cfg.get("mode", "observe_only"))
    effective_mode = requested_mode
    degraded_by_governor = False
    degradation_reason = None
    require_ollama = bool(cfg.get("require_ollama", False))
    safe_only = bool(cfg.get("safe_only", True))

    if not ollama_ok and require_ollama:
        effective_mode = "observe_only"
        preflight_errors.append("ollama_required_but_unavailable")

    try:
        decision = decide_work_mode(probe, blood, requested_mode)
        allowed = decision.get("effective_mode", "observe_only")
        if WORK_MODE_RANK.get(effective_mode, 0) > WORK_MODE_RANK.get(allowed, 0):
            effective_mode = allowed
            degraded_by_governor = True
            degradation_reason = decision.get("reason") or f"{requested_mode} degradado a {allowed} por gobernador."
    except Exception as exc:
        preflight_errors.append(f"governor_decision_failed: {exc}")

    if effective_mode in ("blocked", "cooldown"):
        _ALWAYS_ON_STATE["status"] = "blocked_by_governor"
        _ALWAYS_ON_STATE["error"] = f"Governor bloquea: effective_mode={effective_mode}"
        return {"status": "blocked", "effective_mode": effective_mode, "preflight_errors": preflight_errors,
                "message": "ALWAYS-ON no puede iniciar: recursos insuficientes.", "config_source": cfg["_config_source"]}

    # ── Start background runtime ──
    try:
        result = start_internal_runtime_background(
            db_path=db_path, runs_dir=runs_dir, mode=effective_mode,
            interval_seconds=int(cfg.get("interval_seconds", 60)),
            max_cycles=cfg.get("_max_cycles_param"),
        )
    except Exception as exc:
        _ALWAYS_ON_STATE["status"] = "start_failed"
        _ALWAYS_ON_STATE["error"] = str(exc)
        return {"status": "error", "message": f"Error al iniciar runtime: {exc}",
                "preflight_errors": preflight_errors, "config_source": cfg["_config_source"]}

    now_utc = datetime.now(timezone.utc).isoformat()
    _ALWAYS_ON_STATE["effective_mode"] = effective_mode
    _ALWAYS_ON_STATE["degraded_by_governor"] = degraded_by_governor
    _ALWAYS_ON_STATE["degradation_reason"] = degradation_reason
    _ALWAYS_ON_STATE["background_thread_alive"] = True
    _ALWAYS_ON_STATE["last_start_at"] = now_utc
    _ALWAYS_ON_STATE["last_cycle_at"] = now_utc
    _ALWAYS_ON_STATE["started_at"] = now_utc
    _ALWAYS_ON_STATE["status"] = "running"
    _ALWAYS_ON_STATE["error"] = None

    # ── Self-test on start ──
    self_test_result = None
    if bool(cfg.get("self_test_on_start", True)):
        try:
            self_test_result = run_self_test_cycle(mode="safe", db_path=db_path, runs_dir=runs_dir)
            _ALWAYS_ON_STATE["last_self_test_status"] = self_test_result
        except Exception as st_exc:
            self_test_result = {"status": "error", "error": str(st_exc)}
            _ALWAYS_ON_STATE["last_self_test_status"] = self_test_result

    try:
        record_internal_runtime_event(
            "always_on_started", "always_on",
            {"configured_mode": requested_mode, "effective_mode": effective_mode,
             "degraded_by_governor": degraded_by_governor, "degradation_reason": degradation_reason,
             "interval_seconds": cfg.get("interval_seconds"), "max_cycles": cfg.get("max_cycles"),
             "config_source": cfg["_config_source"], "preflight_errors": preflight_errors},
            severity="info",
        )
    except Exception:
        pass

    start_result = {
        "status": "started",
        "configured_mode": requested_mode,
        "effective_mode": effective_mode,
        "degraded_by_governor": degraded_by_governor,
        "degradation_reason": degradation_reason,
        "interval_seconds": cfg.get("interval_seconds"),
        "config_source": cfg["_config_source"],
        "background_thread_alive": True,
        "message": f"ALWAYS-ON iniciado en modo {effective_mode} cada {cfg.get('interval_seconds')}s.",
        "preflight_errors": preflight_errors if preflight_errors else None,
        "self_test": self_test_result,
        "runtime_result": result,
    }
    _ALWAYS_ON_STATE["last_start_result"] = start_result
    return start_result


def stop_always_on(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    global _ALWAYS_ON_STATE
    try:
        result = stop_internal_runtime_background(db_path=db_path, runs_dir=runs_dir)
    except Exception as exc:
        _ALWAYS_ON_STATE["status"] = "stop_failed"
        _ALWAYS_ON_STATE["error"] = str(exc)
        return {"status": "error", "message": f"Error al detener: {exc}"}

    _ALWAYS_ON_STATE["enabled"] = False
    _ALWAYS_ON_STATE["background_thread_alive"] = False
    _ALWAYS_ON_STATE["status"] = "stopped"
    return {"status": "stopped", "message": "ALWAYS-ON runtime detenido.", "runtime_result": result}


def restart_always_on(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
) -> dict[str, Any]:
    stop_always_on(db_path=db_path, runs_dir=runs_dir)
    return start_always_on_if_enabled(db_path=db_path, runs_dir=runs_dir)
