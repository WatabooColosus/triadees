from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class HealthSensors:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def inspect(self) -> dict[str, Any]:
        sensors: dict[str, Any] = {
            "checked_at": datetime.now(UTC).isoformat(),
            "db": self._check_db(),
            "disk": self._check_disk(),
            "memory": self._check_memory(),
            "heartbeat": self._check_heartbeat(),
            "leases": self._check_leases(),
            "queue": self._check_queue(),
        }
        healthy = all(
            s.get("ok", False) for s in sensors.values() if isinstance(s, dict)
        )
        sensors["healthy"] = healthy
        return sensors

    def _check_db(self) -> dict[str, Any]:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                quick = str(conn.execute("PRAGMA quick_check").fetchone()[0])
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                return {
                    "ok": quick == "ok",
                    "quick_check": quick,
                    "table_count": len(tables),
                }
        except (sqlite3.Error, OSError) as exc:
            return {"ok": False, "error": type(exc).__name__}

    def _check_disk(self) -> dict[str, Any]:
        try:
            import shutil

            usage = shutil.disk_usage(self.db_path.parent)
            free_gb = usage.free / (1024**3)
            return {
                "ok": free_gb > 2.0,
                "free_gb": round(free_gb, 1),
                "total_gb": round(usage.total / (1024**3), 1),
            }
        except OSError:
            return {"ok": False, "error": "disk_check_failed"}

    def _check_memory(self) -> dict[str, Any]:
        try:
            import psutil  # type: ignore[import-untyped]

            mem = psutil.virtual_memory()
            avail_gb = mem.available / (1024**3)
            return {
                "ok": avail_gb > 1.0,
                "available_gb": round(avail_gb, 1),
                "percent": mem.percent,
            }
        except (ImportError, OSError):
            return {"ok": False, "error": "memory_check_failed"}

    def _check_heartbeat(self) -> dict[str, Any]:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                row = conn.execute(
                    "SELECT updated_at FROM live_runtime_heartbeat ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return {"ok": False, "error": "no_heartbeat_found"}
                ts = datetime.fromisoformat(row[0])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                age = (datetime.now(UTC) - ts).total_seconds()
                return {
                    "ok": age < 180,
                    "age_seconds": int(age),
                }
        except (sqlite3.Error, OSError, ValueError) as exc:
            return {"ok": False, "error": type(exc).__name__}

    def _check_leases(self) -> dict[str, Any]:
        """Leases vencidos en la cola viva.

        Vigilaba `worker_tasks.status='claimed'`: la cola legacy, sin una sola
        fila `claimed` en toda su historia y sin escrituras desde 2026-07-29. El
        sensor daba `ok` siempre, así que `lease_supervision` no nacía nunca y
        `AutonomousTaskStore.recover_expired()` no llegaba a llamarse en
        producción. Se encontró con dos tareas atascadas 12 y 6 minutos con el
        lease vencido mientras el runtime se declaraba sano.

        Los estados y la comparación son los mismos que usa `recover_expired()`,
        a propósito: quien detecta y quien recupera deben mirar lo mismo o el
        sensor volvería a mentir.
        """
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "autonomous_tasks" not in tables:
                    return {
                        "ok": True,
                        "stale_leases": 0,
                        "note": "no_autonomous_tasks_table",
                    }
                stale = conn.execute(
                    """SELECT COUNT(*) FROM autonomous_tasks
                    WHERE status IN ('leased','running')
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at<=?""",
                    (datetime.now(UTC).isoformat(),),
                ).fetchone()[0]
                return {"ok": stale == 0, "stale_leases": int(stale)}
        except (sqlite3.Error, OSError) as exc:
            return {"ok": False, "error": type(exc).__name__}

    def _check_queue(self) -> dict[str, Any]:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "worker_tasks" not in tables:
                    return {"ok": True, "pending": 0}
                pending = conn.execute(
                    "SELECT COUNT(*) FROM worker_tasks WHERE status='pending'"
                ).fetchone()[0]
                return {"ok": int(pending) < 100, "pending": int(pending)}
        except (sqlite3.Error, OSError) as exc:
            return {"ok": False, "error": type(exc).__name__}
