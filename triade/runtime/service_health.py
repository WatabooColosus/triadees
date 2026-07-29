"""Sondas de progreso del runtime; no confunden PID vivo con servicio sano."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from triade.core.resource_probe import build_resource_probe

HealthState = Literal[
    "healthy", "degraded", "stalled", "recovering", "critical", "stopped"
]


@dataclass(frozen=True, slots=True)
class RuntimeHealth:
    state: HealthState
    reasons: tuple[str, ...]
    metrics: dict[str, Any]
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ServiceHealth:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        heartbeat_stale_seconds: int = 180,
        cycle_stale_seconds: int = 900,
        disk_critical_gb: float = 2,
        ram_critical_gb: float = 1,
    ) -> None:
        self.db_path = Path(db_path)
        self.heartbeat_stale_seconds = heartbeat_stale_seconds
        self.cycle_stale_seconds = cycle_stale_seconds
        self.disk_critical_gb = disk_critical_gb
        self.ram_critical_gb = ram_critical_gb

    def inspect(
        self,
        *,
        process_running: bool | None = None,
        ollama_probe: dict[str, Any] | None = None,
    ) -> RuntimeHealth:
        now = datetime.now(UTC)
        reasons: list[str] = []
        metrics: dict[str, Any] = {"process_running": process_running}
        if process_running is False:
            reasons.append("process_stopped")
        db_critical = False
        stalled = False
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout=2000")
                quick = str(conn.execute("PRAGMA quick_check").fetchone()[0])
                metrics["sqlite"] = quick
                if quick != "ok":
                    reasons.append("sqlite_integrity_failed")
                    db_critical = True
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if "worker_tasks" in tables:
                    counts = {
                        str(row[0]): int(row[1])
                        for row in conn.execute(
                            "SELECT status,COUNT(*) FROM worker_tasks GROUP BY status"
                        )
                    }
                    metrics["queue"] = counts
                    oldest = conn.execute(
                        "SELECT created_at FROM worker_tasks WHERE status IN ('pending','running','claimed') ORDER BY created_at LIMIT 1"
                    ).fetchone()
                    age = self._age_seconds(oldest[0], now) if oldest else None
                    metrics["oldest_active_task_seconds"] = age
                    if (
                        age is not None
                        and age > self.cycle_stale_seconds
                        and counts.get("completed", 0) == 0
                    ):
                        reasons.append("queue_not_progressing")
                        stalled = True
                if "worker_runs" in tables:
                    run = conn.execute(
                        "SELECT status,started_at,finished_at FROM worker_runs ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    metrics["last_worker_run"] = dict(run) if run else None
                    if (
                        run
                        and run["status"] == "running"
                        and self._age_seconds(run["started_at"], now)
                        > self.cycle_stale_seconds
                    ):
                        reasons.append("worker_cycle_stalled")
                        stalled = True
                if "worker_state" in tables:
                    heartbeat = conn.execute(
                        "SELECT updated_at,value_json FROM worker_state WHERE key IN ('workers','scheduler_heartbeat') ORDER BY updated_at DESC LIMIT 1"
                    ).fetchone()
                    age = (
                        self._age_seconds(heartbeat["updated_at"], now)
                        if heartbeat
                        else None
                    )
                    metrics["heartbeat_age_seconds"] = age
                    if age is None or age > self.heartbeat_stale_seconds:
                        reasons.append("heartbeat_stale")
                        stalled = True
                if "worker_events" in tables:
                    repeated = conn.execute(
                        "SELECT COUNT(*) FROM worker_events WHERE status IN ('error','failed') AND created_at>=datetime('now','-15 minutes')"
                    ).fetchone()[0]
                    metrics["recent_repeated_errors"] = int(repeated)
                    if repeated >= 5:
                        reasons.append("repeated_worker_errors")
        except (sqlite3.Error, OSError) as exc:
            metrics["sqlite_error"] = type(exc).__name__
            reasons.append("sqlite_unavailable_or_locked")
            db_critical = True

        resources = build_resource_probe()
        metrics["resources"] = resources
        if float(resources.get("disk", {}).get("free_gb") or 0) < self.disk_critical_gb:
            reasons.append("disk_critical")
            db_critical = True
        if (
            float(resources.get("memory", {}).get("available_gb") or 0)
            < self.ram_critical_gb
        ):
            reasons.append("memory_critical")
            db_critical = True
        thermal = resources.get("thermal", {}).get("thermal_status")
        if thermal in {"high", "critical"}:
            reasons.append(f"temperature_{thermal}")

        ollama = ollama_probe if ollama_probe is not None else self._ollama_probe()
        metrics["ollama"] = ollama
        if not bool(ollama.get("ollama_ok") or ollama.get("ok")):
            reasons.append("ollama_unavailable")

        if process_running is False:
            state: HealthState = "stopped"
        elif db_critical:
            state = "critical"
        elif stalled:
            state = "stalled"
        elif reasons:
            state = "degraded"
        else:
            state = "healthy"
        return RuntimeHealth(
            state, tuple(dict.fromkeys(reasons)), metrics, now.isoformat()
        )

    @staticmethod
    def _age_seconds(value: Any, now: datetime) -> float:
        if value is None:
            return float("inf")
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return max(0.0, (now - parsed).total_seconds())

    @staticmethod
    def _ollama_probe() -> dict[str, Any]:
        try:
            from triade.core.ollama_blood import check_ollama_blood

            result = check_ollama_blood()
            return (
                dict(result)
                if isinstance(result, dict)
                else {"ok": False, "error_type": "invalid_probe_result"}
            )
        except Exception as exc:
            return {"ok": False, "error_type": type(exc).__name__}

    @staticmethod
    def serializable_metrics(metrics: dict[str, Any]) -> str:
        return json.dumps(metrics, ensure_ascii=False, default=str, sort_keys=True)
