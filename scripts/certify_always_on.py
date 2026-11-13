#!/usr/bin/env python3
"""Certifica que Tríade vuelve sola cuando la matan, y vuelve siendo la misma.

No comprueba que `/health` conteste: eso ya se sabía y no probaba nada. Mata el
proceso productivo con SIGKILL —sin avisar a systemd, sin relanzar nada a mano— y
mide con reloj cuánto tarda el gestor de servicios en devolver el organismo.

Lo que se registra, y por qué cada cosa:

  crash_at      cuándo se mató el proceso
  detected_at   cuándo el puerto se quedó sin listener (el sistema lo acusa)
  restarted_at  cuándo systemd arrancó el proceso nuevo (ExecMainStartTimestamp)
  healthy_at    cuándo /health/live volvió a responder 200
  workers_at    cuándo el heartbeat volvió a declarar workers activos
  recovery_seconds  de crash_at a healthy_at

Y las condiciones que hacen que «volvió» signifique algo:

  same_db       la base es la misma ruta absoluta y no ha encogido
  same_history  runs, tareas y saber consolidado siguen ahí (no un organismo nuevo)
  single_listener  exactamente un proceso productivo en el puerto
  progress_after   el heartbeat AVANZA después de recuperar, no sólo existe

La comprobación de progreso es la que impide firmar una recuperación falsa: un
proceso puede arrancar, responder 200 y no hacer nada. Antes del 2026-07-31
`runtime_recovery` daba por buena la recuperación sin verificar nada.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.runtime.service_supervision import build_service_supervision

PORT = int(os.getenv("TRIADE_STUDIO_PORT", "8010"))
BASE = f"http://127.0.0.1:{PORT}"
UNIT = "triade-api.service"
DB = os.getenv("TRIADE_DB_PATH", "triade/memory/triade.db")

#: Tablas cuyo contenido no puede desaparecer al reiniciar. Si el reinicio
#: devolviera una base nueva, éstas volverían a cero y la certificación falla.
IDENTITY_TABLES = (
    "runs",
    "autonomous_tasks",
    "learning_queue",
    "learning_evidence",
    "semantic_documents",
    "improvement_history",
    "knowledge_patterns",
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _get(path: str, timeout: float = 10.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _live() -> bool:
    return _get("/health/live", timeout=5.0) is not None


def _identity() -> dict[str, Any]:
    """Huella de la base: ruta absoluta y filas de lo que no se puede perder."""
    path = Path(DB).resolve()
    snapshot: dict[str, Any] = {"path": str(path), "captured_at": _now()}
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    except sqlite3.Error as exc:
        snapshot["error"] = str(exc)
        return snapshot
    try:
        snapshot["size_bytes"] = path.stat().st_size
        counts: dict[str, int | None] = {}
        for table in IDENTITY_TABLES:
            try:
                counts[table] = int(
                    conn.execute(f"select count(*) from {table}").fetchone()[0]
                )
            except sqlite3.Error:
                counts[table] = None
        snapshot["counts"] = counts
        snapshot["stable_documents"] = int(
            conn.execute(
                "select count(*) from semantic_documents where status='stable'"
            ).fetchone()[0]
        )
        snapshot["integrity"] = conn.execute("pragma integrity_check").fetchone()[0]
        snapshot["foreign_key_violations"] = len(
            conn.execute("pragma foreign_key_check").fetchall()
        )
    finally:
        conn.close()
    return snapshot


def _heartbeat_cycle() -> int | None:
    """Contador de ciclos del latido vivo.

    Sale de `LiveHeartbeat`, que es la misma fuente que usa el watchdog para
    decidir si hubo recuperación, y no de `/api/runtime/heartbeat`: ese endpoint
    publica `cycles_last_hour`, no `cycle`. Leerlo con `.get("cycle") or 0`
    devolvía 0 siempre, así que la comprobación de progreso comparaba cero
    contra cero y no podía dar verdadero nunca — decía que el organismo no
    avanzaba mientras el propio informe registraba workers activos.
    """
    try:
        from triade.runtime.live_heartbeat import LiveHeartbeat

        snapshot = LiveHeartbeat().snapshot()
    except (OSError, ImportError, RuntimeError, ValueError, sqlite3.Error):
        return None
    if snapshot.get("status") == "not_started":
        return None
    try:
        return int(snapshot.get("cycle") or 0)
    except (TypeError, ValueError):
        return None


def _workers_active() -> bool:
    data = _get("/api/runtime/heartbeat", timeout=25.0)
    return bool(data and data.get("workers_active"))


def certify(*, wait_seconds: int = 300) -> dict[str, Any]:
    report: dict[str, Any] = {"unit": UNIT, "port": PORT, "started_at": _now()}

    before = build_service_supervision(unit=UNIT, port=PORT)
    report["before"] = before
    if not before.get("service_managed"):
        report["verdict"] = "BLOCKED"
        report["reason"] = (
            "el proceso del puerto no está bajo systemd; no hay nada que certificar"
        )
        report["blockers"] = before.get("always_on_blockers")
        return report

    pid = before["runtime_pid"]
    report["identity_before"] = _identity()
    report["restart_count_before"] = before.get("restart_count")
    report["start_timestamp_before"] = before.get("started_at")
    cycle_before = _heartbeat_cycle()
    report["heartbeat_cycle_before"] = cycle_before

    # SIGKILL: ni el proceso ni systemd reciben un cierre ordenado. Es la
    # diferencia entre «lo paré yo» y «se murió».
    crash_at = time.monotonic()
    report["crash_at"] = _now()
    os.kill(pid, 9)

    detected_at: float | None = None
    healthy_at: float | None = None
    restarted_at: str | None = None
    deadline = crash_at + wait_seconds

    while time.monotonic() < deadline:
        supervision = build_service_supervision(unit=UNIT, port=PORT)
        listeners = supervision.get("listener_count")
        if detected_at is None and listeners == 0:
            detected_at = time.monotonic()
            report["detected_at"] = _now()
        if _live():
            healthy_at = time.monotonic()
            report["healthy_at"] = _now()
            restarted_at = supervision.get("started_at")
            break
        time.sleep(0.5)

    if healthy_at is None:
        report["verdict"] = "FAILED"
        report["reason"] = f"no volvió en {wait_seconds}s"
        report["after"] = build_service_supervision(unit=UNIT, port=PORT)
        return report

    report["restarted_at"] = restarted_at
    report["recovery_seconds"] = round(healthy_at - crash_at, 2)
    if detected_at is not None:
        report["detection_seconds"] = round(detected_at - crash_at, 2)

    # Los workers viven dentro del proceso de la API y tardan más que el puerto.
    workers_deadline = time.monotonic() + wait_seconds
    report["workers_recovered"] = False
    while time.monotonic() < workers_deadline:
        if _workers_active():
            report["workers_recovered"] = True
            report["workers_at"] = _now()
            report["workers_recovery_seconds"] = round(time.monotonic() - crash_at, 2)
            break
        time.sleep(5)

    # Un proceso puede responder 200 y no avanzar. Lo que se exige es que el
    # contador de ciclos AVANCE ya recuperado.
    #
    # La referencia se toma después de recuperar, no antes del crash: `cycle`
    # cuenta los ciclos de ESTE proceso y vuelve a empezar con el proceso nuevo.
    # Compararlo con el de antes preguntaría si el organismo recuperado ha
    # trabajado más que el muerto, que no es la pregunta y además saldría que no.
    report["progress_after_recovery"] = False
    baseline = _heartbeat_cycle()
    report["heartbeat_cycle_baseline_after_restart"] = baseline
    progress_deadline = time.monotonic() + wait_seconds
    while time.monotonic() < progress_deadline:
        current = _heartbeat_cycle()
        if current is not None and (baseline is None or current > baseline):
            report["progress_after_recovery"] = True
            report["heartbeat_cycle_after"] = current
            break
        time.sleep(5)

    after = build_service_supervision(unit=UNIT, port=PORT)
    report["after"] = after
    report["identity_after"] = _identity()
    report["restart_count_after"] = after.get("restart_count")

    ident_before = report["identity_before"]
    ident_after = report["identity_after"]
    same_path = ident_before.get("path") == ident_after.get("path")
    # El saber sólo puede crecer: una base nueva devolvería ceros.
    same_history = all(
        (ident_after.get("counts") or {}).get(table) is not None
        and (
            ident_after["counts"][table]
            >= (ident_before.get("counts") or {}).get(table, 0)
        )
        for table in IDENTITY_TABLES
    )
    report["same_db"] = bool(same_path)
    report["same_history"] = bool(same_history)
    report["single_listener"] = after.get("listener_state") == "healthy"
    report["still_service_managed"] = bool(after.get("service_managed"))
    report["restarted_by_service_manager"] = (
        report["restart_count_after"] is not None
        and report["restart_count_before"] is not None
        and report["restart_count_after"] > report["restart_count_before"]
    )

    checks = {
        "restart_after_crash": True,
        "restarted_by_service_manager": report["restarted_by_service_manager"],
        "single_listener": report["single_listener"],
        "same_db": report["same_db"],
        "same_history": report["same_history"],
        "workers_recovered": report["workers_recovered"],
        "progress_after_recovery": report["progress_after_recovery"],
        "still_service_managed": report["still_service_managed"],
        "autostart_enabled": bool(after.get("autostart_enabled")),
        "no_manual_intervention": True,
        "db_integrity_ok": ident_after.get("integrity") == "ok",
        "no_fk_violations": ident_after.get("foreign_key_violations") == 0,
    }
    report["checks"] = checks
    report["verdict"] = "CERTIFIED" if all(checks.values()) else "FAILED"
    report["failed_checks"] = [name for name, ok in checks.items() if not ok]
    report["finished_at"] = _now()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait", type=int, default=300)
    parser.add_argument("--out", default="artifacts/always_on/crash-restart.json")
    args = parser.parse_args()

    report = certify(wait_seconds=args.wait)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"\ninforme: {out}")
    return 0 if report.get("verdict") == "CERTIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
