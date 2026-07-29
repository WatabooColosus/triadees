"""Cola persistente de tareas para Living Workers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.core.contracts import utc_now
from triade.runtime.task_leases import ACTIVE, AutonomousTaskStore

from .contracts import WORKER_TASK_TYPES, WorkerTask
from .state_store import WorkerStateStore


class WorkerTaskQueue:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.store = WorkerStateStore(db_path=db_path)
        self.canonical = AutonomousTaskStore(db_path=db_path)

    def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        priority: int = 50,
        run_ref: str | None = None,
    ) -> WorkerTask:
        if task_type not in WORKER_TASK_TYPES:
            raise ValueError(f"worker task_type inválido: {task_type}")
        clean_payload = payload or {}
        payload_hash = self.canonical.payload_hash(clean_payload)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" for _ in ACTIVE)
            row = conn.execute(
                f"""SELECT task_id FROM autonomous_tasks
                WHERE task_type=? AND payload_hash=? AND status IN ({placeholders})
                ORDER BY created_at,task_id LIMIT 1""",
                (task_type, payload_hash, *sorted(ACTIVE)),
            ).fetchone()
        if row is not None:
            existing = self.canonical.get(str(row["task_id"]))
            if existing is not None:
                return self._from_canonical(existing)
        canonical = self.canonical.enqueue(
            task_type,
            clean_payload,
            idempotency_key=f"worker-v2:{run_ref or 'direct'}:{uuid4().hex}",
            priority=priority,
        )
        from triade.runtime.wake_bus import wake_runtime

        wake_runtime(self.db_path)
        return self._from_canonical(canonical)

    def enqueue_defaults(self, run_ref: str | None = None) -> list[WorkerTask]:
        tasks = []
        for index, task_type in enumerate(WORKER_TASK_TYPES):
            tasks.append(
                self.enqueue(
                    task_type,
                    payload={"scheduled": True},
                    priority=10 + index,
                    run_ref=run_ref,
                )
            )
        return tasks

    def claim_next(self) -> WorkerTask | None:
        return self.store.claim_next_task()

    def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if status:
                rows = conn.execute(
                    "SELECT * FROM autonomous_tasks WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM autonomous_tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self.canonical._decode(row) for row in rows]

    @staticmethod
    def _from_canonical(task: dict[str, Any]) -> WorkerTask:
        return WorkerTask(
            id=str(task["task_id"]),
            task_type=str(task["task_type"]),
            payload=dict(task.get("payload") or {}),
            priority=int(task.get("priority") or 50),
            status=str(task.get("status") or "pending"),
            run_ref=None,
            created_at=str(task.get("created_at") or utc_now()),
            error=str(task.get("last_error") or "") or None,
        )
