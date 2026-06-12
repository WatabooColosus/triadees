"""Planificador de tareas Living Workers."""

from __future__ import annotations

from pathlib import Path

from .contracts import WORKER_TASK_TYPES, WorkerRunConfig
from .task_queue import WorkerTaskQueue


class WorkerScheduler:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.queue = WorkerTaskQueue(db_path=db_path)

    def schedule_cycle(self, run_ref: str, config: WorkerRunConfig) -> list[dict]:
        tasks = self.queue.enqueue_defaults(run_ref=run_ref)
        return [task.to_dict() for task in tasks]

    def task_types(self) -> tuple[str, ...]:
        return WORKER_TASK_TYPES
