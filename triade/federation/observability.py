"""Observabilidad y exportación auditable para la federación de Tríade."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


class FederatedObservability:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            nodes = self._group(conn, "federated_nodes_v2", "state")
            jobs = self._group(conn, "federated_jobs", "status")
            assessments = self._group(conn, "federated_evidence_assessments", "decision")
            exchanges = self._group(conn, "federated_exchanges_v2", "status")
            recent_failures = self._recent_failures(conn)
        return {
            "schema_version": "1.0.0",
            "nodes": nodes,
            "jobs": jobs,
            "assessments": assessments,
            "exchanges": exchanges,
            "recent_failures": recent_failures,
        }

    def export_bundle(self, *, node_id: str | None = None, job_id: str | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            bundle = {
                "schema_version": "1.0.0",
                "filters": {"node_id": node_id, "job_id": job_id},
                "snapshot": self.snapshot(),
                "nodes": self._rows(conn, "federated_nodes_v2", "node_id", node_id),
                "node_events": self._rows(conn, "federated_node_events", "node_id", node_id),
                "jobs": self._rows(conn, "federated_jobs", "job_id", job_id),
                "job_events": self._rows(conn, "federated_job_events", "job_id", job_id),
                "exchanges": self._rows(conn, "federated_exchanges_v2", "message_id", None),
                "exchange_events": self._rows(conn, "federated_exchange_events_v2", "message_id", None),
                "assessments": self._rows(conn, "federated_evidence_assessments", "job_id", job_id),
            }
        canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":"), default=str)
        return {
            "bundle": bundle,
            "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def _group(self, conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
        if not self._table_exists(conn, table):
            return {}
        rows = conn.execute(
            f"SELECT {column}, COUNT(*) AS total FROM {table} GROUP BY {column} ORDER BY {column}"
        ).fetchall()
        return {str(row[column]): int(row["total"]) for row in rows}

    def _rows(
        self,
        conn: sqlite3.Connection,
        table: str,
        filter_column: str,
        filter_value: str | None,
    ) -> list[dict[str, Any]]:
        if not self._table_exists(conn, table):
            return []
        if filter_value is None:
            rows = conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE {filter_column} = ? ORDER BY rowid",
                (filter_value,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _recent_failures(self, conn: sqlite3.Connection) -> list[dict[str, Any]]:
        if not self._table_exists(conn, "federated_jobs"):
            return []
        rows = conn.execute(
            """SELECT job_id, remote_node_id, capability, status, updated_at
            FROM federated_jobs WHERE status IN ('failed', 'rejected')
            ORDER BY updated_at DESC LIMIT 20"""
        ).fetchall()
        return [dict(row) for row in rows]
