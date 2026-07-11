"""Resumen operativo del Regression Gate para doctor y API."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class RegressionObservability:
    """Construye un snapshot de salud sin modificar estado."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def snapshot(self) -> dict[str, Any]:
        if not self.db_path.exists():
            return self._empty("not_initialized", schema_ready=False)
        with self._connect() as conn:
            report_rows = self._safe_rows(
                conn,
                "SELECT decision, COUNT(*) AS count FROM regression_reports GROUP BY decision",
            )
            quarantine_active = self._safe_scalar(
                conn,
                "SELECT COUNT(*) FROM regression_quarantine WHERE active = 1",
            )
            stable_count = self._safe_scalar(
                conn,
                "SELECT COUNT(*) FROM stable_capability_state",
            )
            protection_active = self._safe_scalar(
                conn,
                "SELECT COUNT(*) FROM capability_protection_rules WHERE status = 'active'",
            )
            protection_immutable = self._safe_scalar(
                conn,
                "SELECT COUNT(*) FROM capability_protection_rules WHERE immutable = 1 AND status = 'active'",
            )
            rollback_rows = self._safe_rows(
                conn,
                "SELECT status, COUNT(*) AS count FROM rollback_operations GROUP BY status",
            )
            schema_ready = self._has_tables(
                conn,
                {
                    "regression_reports",
                    "regression_quarantine",
                    "stable_capability_state",
                },
            )
        decisions = {str(row["decision"]): int(row["count"]) for row in report_rows}
        rollbacks = {str(row["status"]): int(row["count"]) for row in rollback_rows}
        unhealthy = quarantine_active > 0 or decisions.get("fail", 0) > 0 or decisions.get("invalid", 0) > 0
        if not schema_ready:
            status = "not_initialized"
        else:
            status = "attention" if unhealthy else "healthy"
        return {
            "status": status,
            "schema_ready": schema_ready,
            "reports": {
                "total": sum(decisions.values()),
                "by_decision": decisions,
            },
            "quarantine": {"active": quarantine_active},
            "protections": {
                "active": protection_active,
                "immutable": protection_immutable,
            },
            "rollbacks": {
                "total": sum(rollbacks.values()),
                "by_status": rollbacks,
            },
            "stable_capabilities": stable_count,
        }

    @staticmethod
    def _empty(status: str, *, schema_ready: bool) -> dict[str, Any]:
        return {
            "status": status,
            "schema_ready": schema_ready,
            "reports": {"total": 0, "by_decision": {}},
            "quarantine": {"active": 0},
            "protections": {"active": 0, "immutable": 0},
            "rollbacks": {"total": 0, "by_status": {}},
            "stable_capabilities": 0,
        }

    @staticmethod
    def _has_tables(conn: sqlite3.Connection, required: set[str]) -> bool:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        existing = {str(row[0]) for row in rows}
        return required.issubset(existing)

    @staticmethod
    def _safe_scalar(conn: sqlite3.Connection, query: str) -> int:
        try:
            row = conn.execute(query).fetchone()
        except sqlite3.OperationalError:
            return 0
        return int(row[0]) if row else 0

    @staticmethod
    def _safe_rows(conn: sqlite3.Connection, query: str) -> list[sqlite3.Row]:
        try:
            return list(conn.execute(query).fetchall())
        except sqlite3.OperationalError:
            return []
