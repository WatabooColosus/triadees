#!/usr/bin/env python
"""Ventana larga de validación: mide, no opina.

    python scripts/run_long_validation.py --hours 2   --label v1
    python scripts/run_long_validation.py --hours 24  --label v2
    python scripts/run_long_validation.py --hours 72  --label v3

Toma una muestra cada `--interval` minutos y la escribe en JSONL. Cada muestra
lleva el SHA: **si el SHA cambia, la ventana se invalida** y el fichero lo dice.
Reutilizar evidencia de otro commit es la forma más fácil de certificar algo que
nunca corrió.

Se ejecuta contra el runtime que ya esté en pie; no arranca ni para nada. Si la
app se cae a mitad, la muestra lo registra en vez de fallar: una caída es
justamente lo que esta prueba busca detectar.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "triade/memory/triade.db"
HEARTBEAT = "http://localhost:8010/api/runtime/heartbeat"
LIVE = "http://127.0.0.1:8010/health/live"


def sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=10,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _rows(sql: str) -> list[tuple]:
    if not DB.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        return list(conn.execute(sql))
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _scalar(sql: str, defecto: Any = 0) -> Any:
    filas = _rows(sql)
    return filas[0][0] if filas and filas[0] else defecto


def _proc_metrics() -> dict[str, Any]:
    """RSS y descriptores del proceso de la app, si está viva."""
    try:
        out = subprocess.run(
            ["systemctl", "show", "-p", "MainPID", "--value", "triade-api.service"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        pids = [p for p in out.stdout.split() if p.isdigit() and int(p) > 0]
    except (OSError, subprocess.SubprocessError):
        return {"alive": False}
    if not pids:
        return {"alive": False}
    pid = pids[-1]
    datos: dict[str, Any] = {"alive": True, "pid": int(pid)}
    try:
        descriptors = list(Path(f"/proc/{pid}/fd").iterdir())
        datos["fds"] = len(descriptors)
        database = str(DB.resolve())
        sqlite_fds = 0
        for descriptor in descriptors:
            try:
                target = os.readlink(descriptor)
            except OSError:
                continue
            if target == database or target.startswith(f"{database}-"):
                sqlite_fds += 1
        datos["sqlite_fds"] = sqlite_fds
    except OSError:
        datos["fds"] = None
    try:
        for linea in Path(f"/proc/{pid}/status").read_text().splitlines():
            if linea.startswith("VmRSS:"):
                datos["rss_kb"] = int(linea.split()[1])
                break
    except (OSError, ValueError, IndexError):
        datos["rss_kb"] = None
    return datos


def muestra() -> dict[str, Any]:
    wal = DB.with_suffix(".db-wal")
    try:
        with urllib.request.urlopen(HEARTBEAT, timeout=10) as r:
            hb = json.loads(r.read().decode("utf-8"))
        latido = {
            "ok": True,
            "status": hb.get("status"),
            "workers_active": hb.get("workers_active"),
            "mode": hb.get("mode"),
        }
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        latido = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    from triade.runtime.service_supervision import build_service_supervision

    supervision = build_service_supervision(port=8010)
    try:
        with urllib.request.urlopen(LIVE, timeout=5) as response:
            url_available = response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        url_available = False
    return {
        "at": datetime.now(UTC).isoformat(),
        "sha": sha(),
        "heartbeat": latido,
        "process": _proc_metrics(),
        "supervision": {
            "url_available": url_available,
            "listener_count": supervision.get("listener_count"),
            "service_managed": supervision.get("service_managed"),
            "autostart_enabled": supervision.get("autostart_enabled"),
            "restart_count": supervision.get("restart_count"),
        },
        "db_bytes": DB.stat().st_size if DB.exists() else 0,
        "wal_bytes": wal.stat().st_size if wal.exists() else 0,
        "integrity_check": _scalar("PRAGMA integrity_check", "unavailable"),
        "foreign_key_violations": len(_rows("PRAGMA foreign_key_check")),
        "tasks_by_status": {
            str(s): int(n)
            for s, n in _rows("SELECT status,COUNT(*) FROM autonomous_tasks GROUP BY 1")
        },
        "stuck_over_1h": _scalar(
            "SELECT COUNT(*) FROM autonomous_tasks WHERE status IN "
            "('pending','queued','leased','running','retry_wait','recovered') "
            "AND updated_at < datetime('now','-1 hour')"
        ),
        "dead_letters": _scalar(
            "SELECT COUNT(*) FROM autonomous_tasks WHERE status='dead_letter'"
        ),
        "candidates": _scalar("SELECT COUNT(*) FROM learning_queue"),
        "usable_knowledge": _scalar(
            "SELECT COUNT(*) FROM learning_queue WHERE status IN "
            "('evidence_verified','stable')"
        ),
        "stable_learning": _scalar(
            "SELECT COUNT(*) FROM semantic_documents WHERE status='stable'"
        ),
        "learning_events": _scalar("SELECT COUNT(*) FROM learning_evidence"),
        "causal_uses": _scalar("SELECT COUNT(*) FROM learning_usage_events"),
        "goals_completed": _scalar(
            "SELECT COUNT(*) FROM goals WHERE status='completed'"
        ),
        "evidence_by_decision": {
            str(d): int(n)
            for d, n in _rows(
                "SELECT decision,COUNT(*) FROM learning_evidence GROUP BY 1"
            )
        },
        "metabolic_cycles": _scalar("SELECT COUNT(*) FROM metabolic_cycle"),
        "lease_recoveries": _scalar(
            "SELECT COUNT(*) FROM metabolic_receipts "
            "WHERE need_id LIKE 'lease_supervision%'"
        ),
        "watchdog_recoveries": _scalar(
            "SELECT COUNT(*) FROM runtime_recovery_events "
            "WHERE state='runtime_recovered'"
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, required=True)
    ap.add_argument("--interval", type=float, default=10, help="minutos entre muestras")
    ap.add_argument("--label", default="long-run")
    args = ap.parse_args()

    destino = ROOT / "artifacts" / "long-run"
    destino.mkdir(parents=True, exist_ok=True)
    marca = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    fichero = destino / f"{args.label}-{marca}.jsonl"

    sha_inicial = sha()
    fin = time.monotonic() + args.hours * 3600
    n = 0
    invalidada = False

    with fichero.open("w", encoding="utf-8") as fh:
        cabecera = {
            "kind": "header",
            "label": args.label,
            "hours": args.hours,
            "interval_minutes": args.interval,
            "sha_at_start": sha_inicial,
            "started_at": datetime.now(UTC).isoformat(),
        }
        fh.write(json.dumps(cabecera, ensure_ascii=False) + "\n")
        fh.flush()

        while time.monotonic() < fin:
            m = muestra()
            n += 1
            if m["sha"] != sha_inicial:
                m["invalidated"] = "sha_changed"
                invalidada = True
            fh.write(json.dumps(m, ensure_ascii=False) + "\n")
            fh.flush()
            if invalidada:
                break
            time.sleep(args.interval * 60)

        fh.write(
            json.dumps(
                {
                    "kind": "footer",
                    "samples": n,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "invalidated": invalidada,
                    "verdict": "INVALIDATED_SHA_CHANGED" if invalidada else "COMPLETED",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

    print(json.dumps({"file": str(fichero), "samples": n, "invalidated": invalidada}))
    return 1 if invalidada else 0


if __name__ == "__main__":
    raise SystemExit(main())
