"""Arranca el watchdog dentro del proceso que hay, no dentro del que no hay.

El watchdog estaba escrito, probado e inervado —`triade/runtime/watchdog.py` lo
importan cinco módulos—, y llevaba días sin ejecutarse. La razón no era el
código: era el arranque. `scripts/runtime_watchdog.py` está declarado en
`deploy/systemd/triade-watchdog.service`, y **systemd no gobierna este Studio**:
el runtime vive bajo `nohup uvicorn`. La unidad describía un despliegue que no
existe, así que nadie llamaba a `tick()` y `runtime_health_snapshots` llevaba
3,1 días congelada mientras el panel seguía enseñando sus filas viejas.

Los workers ya resolvieron este mismo problema: corren como hilo del proceso de
la API (`core/worker_autostart.py`), no como el servicio declarado. El watchdog
se arranca igual. No sustituye a la unidad de systemd —donde systemd sí mande,
que la use—: lo que hace es que el órgano de vigilancia no dependa de un
supervisor ausente.

Un watchdog que se cae en silencio es peor que no tenerlo, porque promete una
vigilancia que ya no existe. Por eso cada ciclo anota su resultado y un fallo
nunca mata el hilo.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Entre latidos. El mismo valor por defecto que usaba el lanzador de systemd,
#: para que cambiar de supervisor no cambie el comportamiento observado.
DEFAULT_INTERVAL_SECONDS = 60
#: Suelo duro: un watchdog que se despierta cada segundo es otra fuente de carga.
MIN_INTERVAL_SECONDS = 10

_THREAD: threading.Thread | None = None
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "enabled": False,
    "active": False,
    "status": "not_started",
    "interval_seconds": DEFAULT_INTERVAL_SECONDS,
    "ticks": 0,
    "last_tick_at": None,
    "last_state": None,
    "last_error": None,
}


def _interval() -> int:
    raw = os.getenv("TRIADE_WATCHDOG_INTERVAL", str(DEFAULT_INTERVAL_SECONDS))
    try:
        return max(MIN_INTERVAL_SECONDS, int(raw))
    except ValueError:
        return DEFAULT_INTERVAL_SECONDS


def start_watchdog_if_enabled(
    config: dict[str, Any] | None = None,
    *,
    db_path: str | Path = "triade/memory/triade.db",
) -> dict[str, Any]:
    """Arranca el hilo del watchdog si la configuración lo permite.

    Idempotente: si ya hay un hilo vivo no se arranca otro. Dos watchdogs
    recuperando a la vez es exactamente el escenario que el presupuesto de
    recuperaciones de `RuntimeWatchdog` intenta evitar.
    """
    global _THREAD

    settings = config or {}
    enabled = bool(settings.get("runtime_watchdog", True))
    with _LOCK:
        _STATE.update({"enabled": enabled, "interval_seconds": _interval()})
        if not enabled:
            _STATE.update({"active": False, "status": "disabled"})
            return dict(_STATE)
        if _THREAD is not None and _THREAD.is_alive():
            _STATE.update({"active": True, "status": "running"})
            return dict(_STATE)
        _STATE.update({"status": "starting", "last_error": None})
        thread = threading.Thread(
            target=_loop,
            args=(Path(db_path),),
            name="runtime-watchdog",
            daemon=True,
        )
        _THREAD = thread
        thread.start()
        _STATE.update({"active": True, "status": "running"})
        return dict(_STATE)


def watchdog_status() -> dict[str, Any]:
    """Estado observable del watchdog, para que se vea si vigila de verdad."""
    with _LOCK:
        state = dict(_STATE)
    state["thread_alive"] = bool(_THREAD and _THREAD.is_alive())
    return state


def _loop(db_path: Path) -> None:
    from triade.runtime.watchdog import RuntimeWatchdog

    watchdog = RuntimeWatchdog(
        db_path,
        max_recoveries=int(os.getenv("TRIADE_WATCHDOG_MAX_RECOVERIES", "3")),
        recovery_cooldown_seconds=int(
            os.getenv("TRIADE_WATCHDOG_RECOVERY_COOLDOWN_SECONDS", "300")
        ),
    )
    while True:
        interval = _interval()
        try:
            baseline = _heartbeat_cycle()
            result = watchdog.tick(
                process_running=True,
                verify_heartbeat=_heartbeat_verifier(baseline),
            )
            health = result.get("health") or {}
            with _LOCK:
                _STATE.update(
                    {
                        "ticks": int(_STATE.get("ticks", 0)) + 1,
                        "last_tick_at": time.time(),
                        "last_state": health.get("state"),
                        "last_error": None,
                        "status": "running",
                    }
                )
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            # Un watchdog que muere por un error de lectura deja de vigilar sin
            # avisar. Se anota y se sigue: el siguiente ciclo puede ir bien.
            logger.warning("watchdog_tick_failed: %s", exc)
            with _LOCK:
                _STATE.update({"last_error": str(exc), "status": "degraded"})
        time.sleep(interval)


def _heartbeat_cycle() -> int | None:
    """Ciclo actual del heartbeat vivo, o `None` si aún no ha arrancado."""
    try:
        from triade.runtime.live_heartbeat import LiveHeartbeat

        snapshot = LiveHeartbeat().snapshot()
    except Exception:  # noqa: BLE001 -- leer estado no puede matar al watchdog
        return None
    if snapshot.get("status") == "not_started":
        return None
    try:
        return int(snapshot.get("cycle") or 0)
    except (TypeError, ValueError):
        return None


def _heartbeat_verifier(baseline: int | None, *, timeout_seconds: float = 20.0):
    """Exige que el heartbeat **avance** tras recuperar, no que exista.

    Antes de 2026-07-31 no se pasaba verificador y `runtime_recovery` asumía
    `True`, marcando 'runtime_recovered' sin comprobar nada (P1-01).
    """

    def verify() -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            current = _heartbeat_cycle()
            if current is not None and (baseline is None or current > baseline):
                return True
            time.sleep(1.0)
        return False

    return verify
