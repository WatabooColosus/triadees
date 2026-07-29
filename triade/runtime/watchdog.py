"""Watchdog de progreso con recuperación presupuestada."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from triade.runtime.runtime_recovery import RuntimeRecovery
from triade.runtime.service_health import RuntimeHealth, ServiceHealth


class RuntimeWatchdog:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        max_recoveries: int = 3,
    ) -> None:
        self.db_path = Path(db_path)
        self.health = ServiceHealth(self.db_path)
        self.recovery = RuntimeRecovery(self.db_path)
        self.max_recoveries = max(0, max_recoveries)
        self._recoveries = 0

    def tick(
        self,
        *,
        process_running: bool | None = None,
        ollama_probe: dict[str, Any] | None = None,
        stop_workers: Callable[[], Any] | None = None,
        start_workers: Callable[[], Any] | None = None,
        verify_heartbeat: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        status = self.health.inspect(
            process_running=process_running, ollama_probe=ollama_probe
        )
        self._record(status)
        payload: dict[str, Any] = {"health": status.to_dict(), "recovery": None}
        if status.state in {"stalled", "critical", "stopped"}:
            if self._recoveries >= self.max_recoveries:
                payload["recovery"] = {
                    "state": "critical",
                    "reason": "recovery_budget_exhausted",
                }
            else:
                self._recoveries += 1
                payload["recovery"] = self.recovery.recover(
                    ",".join(status.reasons),
                    stop_workers=stop_workers,
                    start_workers=start_workers,
                    verify_heartbeat=verify_heartbeat,
                )
        elif status.state == "healthy":
            self._recoveries = 0
        payload["recovery_attempts"] = self._recoveries
        return payload

    def _record(self, health: RuntimeHealth) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runtime_health_snapshots(state,reason_json,metrics_json,created_at) VALUES(?,?,?,?)",
                (
                    health.state,
                    json.dumps(health.reasons),
                    ServiceHealth.serializable_metrics(health.metrics),
                    health.checked_at,
                ),
            )
