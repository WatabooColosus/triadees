"""Scheduler prioritario de neuronas para TriadeOS.

Calcula prioridades dinámicas basadas en evidencia faltante, staleness,
impacto de dominio, reputación y recursos disponibles. Despierta neuronas
según presupuesto.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.os.contracts import NeuronPriority


class NeuronScheduler:
    """Despierta neuronas por prioridad según estado del sistema."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _ensure_schema(self) -> None:
        migration = Path(__file__).resolve().parents[1] / "memory" / "migrations" / "005_triade_os.sql"
        if migration.exists():
            with self._connect() as conn:
                conn.executescript(migration.read_text(encoding="utf-8"))
        self._ensure_neuron_activity_column()

    def _ensure_neuron_activity_column(self) -> None:
        with self._connect() as conn:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(neuron_activity)").fetchall()}
            if "activation_type" not in cols:
                try:
                    conn.execute("ALTER TABLE neuron_activity ADD COLUMN activation_type TEXT")
                except Exception:
                    pass

    # ── Priority computation ─────────────────────────────────

    def compute_priorities(self) -> list[NeuronPriority]:
        with self._connect() as conn:
            neurons = conn.execute(
                """SELECT id, name, status, domain
                FROM neurons
                WHERE status IN ('experimental', 'active_assistant', 'trusted_worker', 'stable')
                ORDER BY id"""
            ).fetchall()

            if not neurons:
                return []

            now = utc_now()
            priorities: list[NeuronPriority] = []

            for neuron in neurons:
                nid = neuron["id"]
                name = neuron["name"]
                status = neuron["status"]
                domain = neuron["domain"]

                evidence_gap = self._compute_evidence_gap(conn, nid)
                staleness = self._compute_staleness(conn, nid, now)
                impact = self._compute_impact(conn, domain)
                reputation = self._compute_reputation(conn, nid)
                resource_freshness = 1.0

                priority_score = (
                    0.30 * evidence_gap
                    + 0.25 * staleness
                    + 0.20 * impact
                    + 0.15 * reputation
                    + 0.10 * resource_freshness
                )

                reasons = []
                if evidence_gap > 0.6:
                    reasons.append("evidencia_faltante")
                if staleness > 0.5:
                    reasons.append("inactivo_dias")
                if impact > 0.6:
                    reasons.append("dominio_importante")
                if reputation < 0.4:
                    reasons.append("baja_reputacion")

                priorities.append(
                    NeuronPriority(
                        neuron_id=nid,
                        neuron_name=name,
                        priority_score=round(priority_score, 4),
                        evidence_gap=round(evidence_gap, 4),
                        staleness=round(staleness, 4),
                        impact=round(impact, 4),
                        reputation=round(reputation, 4),
                        resource_freshness=round(resource_freshness, 4),
                        reason=", ".join(reasons) or "normal",
                    )
                )

            priorities.sort(key=lambda p: p.priority_score, reverse=True)
            return priorities

    def _compute_evidence_gap(self, conn: sqlite3.Connection, neuron_id: int) -> float:
        required = 5
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM neuron_evidence WHERE neuron_id = ?",
            (neuron_id,),
        ).fetchone()
        has_evidence = int(row["c"]) if row else 0
        return max(0.0, min(1.0, 1.0 - (has_evidence / required)))

    def _compute_staleness(self, conn: sqlite3.Connection, neuron_id: int, now: datetime) -> float:
        row = conn.execute(
            """SELECT created_at FROM neuron_activity
            WHERE neuron_id = ?
            ORDER BY id DESC LIMIT 1""",
            (neuron_id,),
        ).fetchone()
        if not row or not row["created_at"]:
            return 1.0
        try:
            last = datetime.fromisoformat(row["created_at"])
            hours = (now - last).total_seconds() / 3600.0
            return min(1.0, hours / 72.0)
        except (ValueError, TypeError):
            return 1.0

    def _compute_impact(self, conn: sqlite3.Connection, domain: str | None) -> float:
        if not domain:
            return 0.3
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM kg_nodes WHERE domain = ?",
            (domain,),
        ).fetchone()
        count = int(row["c"]) if row else 0
        return min(1.0, count / 20.0)

    def _compute_reputation(self, conn: sqlite3.Connection, neuron_id: int) -> float:
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS successes
            FROM neuron_work_cycles WHERE neuron_id = ?""",
            (neuron_id,),
        ).fetchone()
        if not row or not row["total"]:
            return 0.5
        total = int(row["total"])
        successes = int(row["successes"] or 0)
        if total == 0:
            return 0.5
        activation_row = conn.execute(
            "SELECT COUNT(*) AS c FROM neuron_activity WHERE neuron_id = ?",
            (neuron_id,),
        ).fetchone()
        activations = int(activation_row["c"]) if activation_row else 0
        success_rate = successes / total
        return min(1.0, (success_rate * 0.6) + (min(1.0, activations / 10) * 0.4))

    # ── Schedule wakeups ─────────────────────────────────────

    def schedule_wakeups(self, max_wakeups: int = 5) -> list[dict[str, Any]]:
        priorities = self.compute_priorities()
        if not priorities:
            return []

        scheduled: list[dict[str, Any]] = []
        now = utc_now()

        for p in priorities[:max_wakeups]:
            if p.reputation < 0.2:
                continue

            payload = {
                "neuron_id": p.neuron_id,
                "neuron_name": p.neuron_name,
                "priority_score": p.priority_score,
                "triggered_by": "neuron_scheduler",
            }

            with self._connect() as conn:
                cursor = conn.execute(
                    """INSERT INTO worker_tasks (task_type, status, priority, payload_json, created_at)
                    VALUES ('experimental_neuron_activity', 'pending', ?, ?, ?)""",
                    (int(100 - p.priority_score * 100), json.dumps(payload, ensure_ascii=False), now),
                )
                task_id = int(cursor.lastrowid)

            self._log_priority(p, now)
            scheduled.append({
                "task_id": task_id,
                "neuron_id": p.neuron_id,
                "neuron_name": p.neuron_name,
                "priority_score": p.priority_score,
                "reason": p.reason,
            })

        return scheduled

    def _log_priority(self, p: NeuronPriority, now: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO neuron_priority_log
                (neuron_id, priority_score, evidence_gap, staleness, impact, reputation, resource_freshness, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p.neuron_id,
                    p.priority_score,
                    p.evidence_gap,
                    p.staleness,
                    p.impact,
                    p.reputation,
                    p.resource_freshness,
                    p.reason,
                    now,
                ),
            )

    # ── Usage tracking ───────────────────────────────────────

    def record_activation(self, neuron_id: int, duration_ms: int, success: bool) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO neuron_activity (neuron_id, activation_type, created_at)
                VALUES (?, ?, ?)""",
                (neuron_id, "scheduled" if success else "failed_scheduled", now),
            )

    # ── Doctor ───────────────────────────────────────────────

    def doctor(self) -> dict[str, Any]:
        priorities = self.compute_priorities()
        with self._connect() as conn:
            total_neurons = conn.execute(
                "SELECT COUNT(*) AS c FROM neurons WHERE status IN ('experimental','active_assistant','trusted_worker','stable')"
            ).fetchone()["c"]
            recent_logs = conn.execute(
                "SELECT COUNT(*) AS c FROM neuron_priority_log WHERE created_at >= datetime('now', '-1 day')"
            ).fetchone()["c"]
        return {
            "status": "ok",
            "total_active_neurons": total_neurons,
            "priorities_computed": len(priorities),
            "top_priorities": [p.to_dict() for p in priorities[:5]],
            "recent_priority_logs": recent_logs,
        }
