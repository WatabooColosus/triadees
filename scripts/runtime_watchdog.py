#!/usr/bin/env python3
"""Watchdog foreground. systemd conserva el proceso; este módulo evalúa progreso."""

import json
import os
import time

from triade.runtime.live_heartbeat import LiveHeartbeat
from triade.runtime.watchdog import RuntimeWatchdog


def _heartbeat_cycle() -> int | None:
    """Ciclo actual del heartbeat vivo, o None si aún no ha arrancado."""
    try:
        snapshot = LiveHeartbeat().snapshot()
    except Exception:  # noqa: BLE001 -- el watchdog nunca debe morir por leer estado
        return None
    if snapshot.get("status") == "not_started":
        return None
    try:
        return int(snapshot.get("cycle") or 0)
    except (TypeError, ValueError):
        return None


def _make_heartbeat_verifier(baseline: int | None, *, timeout_seconds: float = 20.0):
    """Devuelve un verificador que exige que el heartbeat AVANCE tras recuperar.

    Antes de 2026-07-31 no se pasaba verificador y `runtime_recovery` asumía
    `True`, marcando 'runtime_recovered' sin comprobar nada (P1-01). Aquí se
    comprueba de verdad: el contador de ciclos debe superar el que había antes
    de la recuperación dentro de una ventana acotada.
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


if __name__ == "__main__":
    interval = max(10, int(os.getenv("TRIADE_WATCHDOG_INTERVAL", "60")))
    watchdog = RuntimeWatchdog(
        max_recoveries=int(os.getenv("TRIADE_WATCHDOG_MAX_RECOVERIES", "3")),
        recovery_cooldown_seconds=int(
            os.getenv("TRIADE_WATCHDOG_RECOVERY_COOLDOWN_SECONDS", "300")
        ),
    )
    while True:
        baseline = _heartbeat_cycle()
        result = watchdog.tick(
            process_running=True,
            verify_heartbeat=_make_heartbeat_verifier(baseline),
        )
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        time.sleep(interval)
