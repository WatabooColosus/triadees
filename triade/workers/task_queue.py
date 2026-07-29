"""Cola persistente de tareas para Living Workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import WORKER_TASK_TYPES, WorkerTask
from .state_store import WorkerStateStore


class WorkerTaskQueue:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.store = WorkerStateStore(db_path=db_path)

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
        existing = self.store.find_active_equivalent(task_type, clean_payload)
        if existing is not None:
            return existing
        task = self.store.enqueue_task(
            task_type, payload=clean_payload, priority=priority, run_ref=run_ref
        )
        from triade.runtime.wake_bus import wake_runtime

        wake_runtime(self.db_path)
        return task

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
        return self.store.list_tasks(status=status, limit=limit)
