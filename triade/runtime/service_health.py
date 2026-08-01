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
    "healthy", "idle", "degraded", "stalled", "recovering", "critical", "stopped"
]

#: Estados de `autonomous_tasks` que cuentan como trabajo elegible: hay algo que
#: hacer AHORA. `retry_wait` y `deferred` quedan fuera a propósito — están
#: esperando su momento, y no avanzar mientras esperan es lo correcto, no un
#: síntoma.
ELIGIBLE_STATUSES = ("pending", "queued", "recovered")

#: Estados en vuelo: alguien los tiene tomados.
IN_FLIGHT_STATUSES = ("leased", "running", "claimed")


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
                # La cola que decide si el organismo avanza es `autonomous_tasks`.
                # Esto leía `worker_tasks`, retirada por trigger desde
                # `019_legacy_retirement.sql` y sin una fila nueva desde el
                # 2026-07-29: la señal que debía detectar un atasco miraba un
                # cadáver, así que la cola siempre parecía vacía y `stalled` no
                # se disparaba nunca.
                if "worker_tasks" in tables:
                    metrics["legacy_queue"] = {
                        str(row[0]): int(row[1])
                        for row in conn.execute(
                            "SELECT status,COUNT(*) FROM worker_tasks GROUP BY status"
                        )
                    }
                if "autonomous_tasks" in tables:
                    counts = {
                        str(row[0]): int(row[1])
                        for row in conn.execute(
                            "SELECT status,COUNT(*) FROM autonomous_tasks GROUP BY status"
                        )
                    }
                    metrics["queue"] = counts
                    eligible = sum(counts.get(s, 0) for s in ELIGIBLE_STATUSES)
                    in_flight = sum(counts.get(s, 0) for s in IN_FLIGHT_STATUSES)
                    metrics["eligible_pending_tasks"] = eligible
                    metrics["active_tasks"] = in_flight
                    placeholders = ",".join(
                        "?" * len(ELIGIBLE_STATUSES + IN_FLIGHT_STATUSES)
                    )
                    oldest = conn.execute(
                        f"SELECT created_at FROM autonomous_tasks WHERE status IN ({placeholders}) ORDER BY created_at LIMIT 1",
                        ELIGIBLE_STATUSES + IN_FLIGHT_STATUSES,
                    ).fetchone()
                    age = self._age_seconds(oldest[0], now) if oldest else None
                    metrics["oldest_active_task_seconds"] = age
                    last_done = conn.execute(
                        "SELECT MAX(updated_at) FROM autonomous_tasks WHERE status='completed'"
                    ).fetchone()
                    last_done_at = last_done[0] if last_done else None
                    metrics["last_task_completed_at"] = last_done_at
                    completed_recently = (
                        last_done_at is not None
                        and self._age_seconds(last_done_at, now)
                        <= self.cycle_stale_seconds
                    )
                    metrics["work_available"] = bool(eligible or in_flight)
                    # Atascado = hay trabajo que hacer, es viejo, y no se ha
                    # cerrado nada en la ventana. Sin trabajo no hay atasco: eso
                    # es `idle`, y se decide más abajo.
                    if (
                        age is not None
                        and age > self.cycle_stale_seconds
                        and not completed_recently
                    ):
                        reasons.append("queue_not_progressing")
                        stalled = True
                run = None
                if "worker_runs" in tables:
                    run = conn.execute(
                        "SELECT status,started_at,finished_at FROM worker_runs ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    metrics["last_worker_run"] = dict(run) if run else None
                heartbeat = None
                heartbeat_source = None
                if "live_runtime_heartbeat" in tables:
                    heartbeat = conn.execute(
                        "SELECT updated_at FROM live_runtime_heartbeat ORDER BY updated_at DESC LIMIT 1"
                    ).fetchone()
                    heartbeat_source = "live_runtime_heartbeat"
                if heartbeat is None and "worker_state" in tables:
                    heartbeat = conn.execute(
                        "SELECT updated_at FROM worker_state WHERE key IN ('workers','scheduler_heartbeat') ORDER BY updated_at DESC LIMIT 1"
                    ).fetchone()
                    heartbeat_source = "worker_state"
                if heartbeat_source is not None:
                    age = (
                        self._age_seconds(heartbeat["updated_at"], now)
                        if heartbeat
                        else None
                    )
                    metrics["heartbeat_source"] = heartbeat_source
                    metrics["heartbeat_age_seconds"] = age
                    if age is None or age > self.heartbeat_stale_seconds:
                        reasons.append("heartbeat_stale")
                        stalled = True
                        if (
                            run
                            and run["status"] == "running"
                            and self._age_seconds(run["started_at"], now)
                            > self.cycle_stale_seconds
                        ):
                            reasons.append("worker_cycle_stalled")
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
        elif metrics.get("work_available") is False:
            # Sano y sin nada que hacer. No es lo mismo que sano y trabajando, y
            # para quien vigila 24/7 esa diferencia es justo la que separa una
            # noche tranquila de un organismo parado. Sólo se declara `idle`
            # cuando se pudo mirar la cola viva: si no se pudo, `work_available`
            # no existe y no se inventa.
            state = "idle"
        else:
            state = "healthy"
        return RuntimeHealth(
            state, tuple(dict.fromkeys(reasons)), metrics, now.isoformat()
        )

    @staticmethod
    def _age_seconds(value: Any, now: datetime) -> float:
        if value is None:
            return float("inf")
        parsed = datetime.fromisoformat(str(value))
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
        except (
            OSError,
            ImportError,
            sqlite3.Error,
            RuntimeError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
        ) as exc:
            return {"ok": False, "error_type": type(exc).__name__}

    @staticmethod
    def serializable_metrics(metrics: dict[str, Any]) -> str:
        return json.dumps(metrics, ensure_ascii=False, default=str, sort_keys=True)
