"""Supervisor mediante servicios separados.

El supervisor monitorea workers, life pulse y capacidades críticas
de forma independiente. Detecta anomalías y emite alertas.
Opera como servicio separado del pipeline principal.
"""

from __future__ import annotations

import json
import sqlite3
import time as _time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

AlertSeverity = Literal["info", "warning", "critical", "fatal"]
SupervisorStatus = Literal["running", "degraded", "stopped"]


@dataclass(frozen=True, slots=True)
class SupervisorAlert:
    alert_id: str
    severity: AlertSeverity
    source: str
    message: str
    details: dict[str, Any]
    created_at: str
    acknowledged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SupervisorReport:
    status: SupervisorStatus
    alerts: tuple[SupervisorAlert, ...]
    components_checked: int
    components_healthy: int
    components_degraded: int
    components_critical: int
    uptime_seconds: float
    last_check_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "alerts": [a.to_dict() for a in self.alerts],
            "components_checked": self.components_checked,
            "components_healthy": self.components_healthy,
            "components_degraded": self.components_degraded,
            "components_critical": self.components_critical,
            "uptime_seconds": self.uptime_seconds,
            "last_check_at": self.last_check_at,
        }


class AutonomousSupervisorService:
    """Servicio supervisor independiente del pipeline."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._start_time = _time.time()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS supervisor_alerts (
                    alert_id TEXT PRIMARY KEY,
                    severity TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    acknowledged INTEGER NOT NULL DEFAULT 0
                )"""
            )

    def check_workers(self) -> list[SupervisorAlert]:
        alerts: list[SupervisorAlert] = []
        try:
            with self._connect() as conn:
                stuck = conn.execute(
                    """SELECT task_id FROM worker_transitions
                    WHERE to_status IN ('claimed', 'running')
                    AND id IN (SELECT MAX(id) FROM worker_transitions GROUP BY task_id)"""
                ).fetchall()
            if len(stuck) > 3:
                alerts.append(SupervisorAlert(
                    alert_id=f"alert-workers-{int(_time.time())}",
                    severity="warning",
                    source="worker_monitor",
                    message=f"{len(stuck)} workers posiblemente stuck",
                    details={"stuck_count": len(stuck)},
                    created_at=utc_now(),
                ))
        except Exception as exc:
            alerts.append(SupervisorAlert(
                alert_id=f"alert-worker-check-{int(_time.time())}",
                severity="critical",
                source="worker_monitor",
                message=f"Error verificando workers: {exc}",
                details={"error": str(exc)},
                created_at=utc_now(),
            ))
        return alerts

    def check_pulse(self) -> list[SupervisorAlert]:
        alerts: list[SupervisorAlert] = []
        try:
            from triade.core.hierarchical_pulse import HierarchicalPulseEngine
            engine = HierarchicalPulseEngine(db_path=self.db_path)
            reading = engine.hierarchical_reading()
            if reading.overall_health == "critical":
                alerts.append(SupervisorAlert(
                    alert_id=f"alert-pulse-{int(_time.time())}",
                    severity="critical",
                    source="pulse_monitor",
                    message=f"Pulso global en estado crítico. Interocepción={reading.interoception_score}",
                    details=reading.to_dict(),
                    created_at=utc_now(),
                ))
            elif reading.overall_health == "degraded":
                alerts.append(SupervisorAlert(
                    alert_id=f"alert-pulse-{int(_time.time())}",
                    severity="warning",
                    source="pulse_monitor",
                    message=f"Pulso global degradado. Interocepción={reading.interoception_score}",
                    details=reading.to_dict(),
                    created_at=utc_now(),
                ))
        except Exception as exc:
            alerts.append(SupervisorAlert(
                alert_id=f"alert-pulse-check-{int(_time.time())}",
                severity="warning",
                source="pulse_monitor",
                message=f"Error verificando pulso: {exc}",
                details={"error": str(exc)},
                created_at=utc_now(),
            ))
        return alerts

    def check_capabilities(self) -> list[SupervisorAlert]:
        alerts: list[SupervisorAlert] = []
        try:
            from triade.capabilities.matrix import CapabilityMatrix
            matrix = CapabilityMatrix(db_path=self.db_path)
            result = matrix.build()
            health = result.get("health", {})
            if health.get("critical_without_baseline", 0) > 0:
                alerts.append(SupervisorAlert(
                    alert_id=f"alert-cap-{int(_time.time())}",
                    severity="critical",
                    source="capability_matrix",
                    message=f"{health['critical_without_baseline']} capacidades críticas sin baseline",
                    details=health,
                    created_at=utc_now(),
                ))
            if health.get("blocked", 0) > 0:
                alerts.append(SupervisorAlert(
                    alert_id=f"alert-cap-blocked-{int(_time.time())}",
                    severity="warning",
                    source="capability_matrix",
                    message=f"{health['blocked']} capacidades bloqueadas",
                    details=health,
                    created_at=utc_now(),
                ))
        except Exception as exc:
            alerts.append(SupervisorAlert(
                alert_id=f"alert-cap-check-{int(_time.time())}",
                severity="warning",
                source="capability_matrix",
                message=f"Error verificando capacidades: {exc}",
                details={"error": str(exc)},
                created_at=utc_now(),
            ))
        return alerts

    def run_check(self) -> SupervisorReport:
        all_alerts: list[SupervisorAlert] = []
        all_alerts.extend(self.check_workers())
        all_alerts.extend(self.check_pulse())
        all_alerts.extend(self.check_capabilities())
        for alert in all_alerts:
            self._persist_alert(alert)
        critical = sum(1 for a in all_alerts if a.severity in {"critical", "fatal"})
        warnings = sum(1 for a in all_alerts if a.severity == "warning")
        if critical > 0:
            status: SupervisorStatus = "degraded"
        elif warnings > 2:
            status = "degraded"
        else:
            status = "running"
        return SupervisorReport(
            status=status,
            alerts=tuple(all_alerts),
            components_checked=3,
            components_healthy=3 - critical - warnings,
            components_degraded=warnings,
            components_critical=critical,
            uptime_seconds=round(_time.time() - self._start_time, 2),
            last_check_at=utc_now(),
        )

    def _persist_alert(self, alert: SupervisorAlert) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO supervisor_alerts(alert_id, severity, source, message, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (alert.alert_id, alert.severity, alert.source, alert.message,
                     json.dumps(alert.details, ensure_ascii=False), alert.created_at),
                )
        except sqlite3.OperationalError:
            pass

    def acknowledge(self, alert_id: str) -> bool:
        with self._connect() as conn:
            conn.execute(
                "UPDATE supervisor_alerts SET acknowledged = 1 WHERE alert_id = ?",
                (alert_id,),
            )
        return True

    def recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM supervisor_alerts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
