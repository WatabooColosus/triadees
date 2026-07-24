"""Workers con máquina de estados formal.

Cada worker transita por estados controlados:
  created → queued → claimed → running → completed/failed/cancelled
Transiciones inválidas son rechazadas y auditadas.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from triade.core.contracts import utc_now

WorkerStatus = Literal["created", "queued", "claimed", "running", "completed", "failed", "cancelled"]

VALID_TRANSITIONS: dict[WorkerStatus, set[WorkerStatus]] = {
    "created": {"queued", "cancelled"},
    "queued": {"claimed", "cancelled"},
    "claimed": {"running", "cancelled"},
    "running": {"completed", "failed"},
    "completed": set(),
    "failed": {"queued"},
    "cancelled": set(),
}


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    task_id: str
    from_status: WorkerStatus
    to_status: WorkerStatus
    reason: str
    actor: str
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkerStateMachine:
    """Máquina de estados para workers con transiciones validadas."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS worker_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    actor TEXT NOT NULL DEFAULT 'system',
                    recorded_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_worker_trans_task ON worker_transitions(task_id, id)"
            )

    def get_status(self, task_id: str) -> WorkerStatus:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT to_status FROM worker_transitions WHERE task_id = ? ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        return str(row["to_status"]) if row else "created"

    def transition(
        self,
        task_id: str,
        to_status: WorkerStatus,
        *,
        reason: str = "",
        actor: str = "system",
    ) -> TransitionRecord:
        current = self.get_status(task_id)
        allowed = VALID_TRANSITIONS.get(current, set())
        if to_status not in allowed:
            raise ValueError(
                f"Transición inválida: {current} → {to_status}. "
                f"Permitidas: {sorted(allowed) or 'ninguna (estado terminal)'}"
            )
        now = utc_now()
        record = TransitionRecord(
            task_id=task_id,
            from_status=current,
            to_status=to_status,
            reason=reason,
            actor=actor,
            timestamp=now,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO worker_transitions(task_id, from_status, to_status, reason, actor, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, current, to_status, reason, actor, now),
            )
        return record

    def force_status(self, task_id: str, to_status: WorkerStatus, *, reason: str = "admin_override") -> TransitionRecord:
        current = self.get_status(task_id)
        now = utc_now()
        record = TransitionRecord(
            task_id=task_id,
            from_status=current,
            to_status=to_status,
            reason=f"FORZADO: {reason}",
            actor="admin",
            timestamp=now,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO worker_transitions(task_id, from_status, to_status, reason, actor, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, current, to_status, record.reason, "admin", now),
            )
        return record

    def history(self, task_id: str) -> list[TransitionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM worker_transitions WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        return [
            TransitionRecord(
                task_id=r["task_id"],
                from_status=r["from_status"],
                to_status=r["to_status"],
                reason=r["reason"],
                actor=r["actor"],
                timestamp=r["recorded_at"],
            )
            for r in rows
        ]

    def stuck_workers(self, timeout_seconds: int = 300) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT task_id, recorded_at FROM worker_transitions
                WHERE to_status IN ('claimed', 'running')
                AND id IN (SELECT MAX(id) FROM worker_transitions GROUP BY task_id)"""
            ).fetchall()
        stuck = []
        now = utc_now()
        for row in rows:
            stuck.append({"task_id": row["task_id"], "since": row["recorded_at"]})
        return stuck

    def doctor(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(DISTINCT task_id) as c FROM worker_transitions").fetchone()["c"]
            by_status = conn.execute(
                """SELECT to_status, COUNT(DISTINCT task_id) as c FROM worker_transitions
                WHERE id IN (SELECT MAX(id) FROM worker_transitions GROUP BY task_id)
                GROUP BY to_status"""
            ).fetchall()
        return {
            "total_tasks": total,
            "by_status": {r["to_status"]: r["c"] for r in by_status},
            "valid_transitions": {k: sorted(v) for k, v in VALID_TRANSITIONS.items()},
        }
