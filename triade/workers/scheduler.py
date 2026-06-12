"""Planificador de tareas Living Workers.

Usa MissionPlanner para decisiones basadas en estado real del sistema.
Si MissionPlanner falla, cae a enqueue_defaults() como fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import WORKER_TASK_TYPES, WorkerRunConfig
from .task_queue import WorkerTaskQueue


class WorkerScheduler:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.queue = WorkerTaskQueue(db_path=db_path)

    def schedule_cycle(self, run_ref: str, config: WorkerRunConfig) -> list[dict]:
        """Planifica un ciclo de tareas. Intenta MissionPlanner; fallback a defaults."""
        try:
            from .mission_planner import MissionPlanner
            planner = MissionPlanner(db_path=self.db_path)
            planned = planner.plan_cycle(run_ref=run_ref)
            if planned:
                return self._enqueue_planned(planned, run_ref=run_ref)
        except Exception:
            pass
        return self._enqueue_defaults(run_ref=run_ref)

    def _enqueue_planned(self, planned: list, run_ref: str | None = None) -> list[dict]:
        """Encola tareas planificadas con metadata de razón y fuente."""
        tasks = []
        for item in planned:
            payload = {
                "reason": item.reason,
                "source": item.source,
                "planner_score": item.priority,
                **(item.payload or {}),
            }
            if item.related_neuron_id is not None:
                payload["related_neuron_id"] = item.related_neuron_id
            if item.related_candidate_id is not None:
                payload["related_candidate_id"] = item.related_candidate_id
            task = self.queue.enqueue(
                task_type=item.task_type,
                payload=payload,
                priority=item.priority,
                run_ref=run_ref,
            )
            tasks.append(task.to_dict())
        return tasks

    def _enqueue_defaults(self, run_ref: str | None = None) -> list[dict]:
        """Fallback: encola todas las tareas por defecto."""
        tasks = self.queue.enqueue_defaults(run_ref=run_ref)
        return [task.to_dict() for task in tasks]

    def task_types(self) -> tuple[str, ...]:
        return WORKER_TASK_TYPES
