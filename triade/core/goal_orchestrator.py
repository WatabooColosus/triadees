"""Orquestador persistente de objetivos y delegación a Living Workers."""

from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any

from triade.workers.task_queue import WorkerTaskQueue

from .capability_resolver import CapabilityResolver
from .planning_graph import PlanningGraph


class GoalOrchestrator:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.resolver = CapabilityResolver()
        self.graph = PlanningGraph(self.db_path)
        self.queue = WorkerTaskQueue(self.db_path)

    def accept(self, request: str, *, run_id: str, source: str = "chat") -> dict[str, Any]:
        resolution = self.resolver.resolve(request)
        if not resolution.actionable:
            return {"status": "not_actionable", "resolution": resolution.to_dict(), "goal_created": False}

        root = self.graph.create_goal(
            title=request[:120], description=request, priority=2,
            metadata={"run_id": run_id, "source": source, "capability": resolution.capability,
                      "resolution": resolution.to_dict(), "budget": {"max_attempts": 3, "max_minutes": 30}},
        )
        step = self.graph.create_goal(
            title=f"Ejecutar capacidad: {resolution.capability}", description=resolution.reason,
            parent_id=root.goal_id, priority=1,
            metadata={"root_goal_id": root.goal_id, "capability": resolution.capability},
        )

        if resolution.requires_human_approval:
            self.graph.update_status(step.goal_id, "awaiting_approval")
            self.graph.update_status(root.goal_id, "awaiting_approval")
            return {"status": "awaiting_approval", "goal_created": True, "goal_id": root.goal_id,
                    "step_id": step.goal_id, "resolution": resolution.to_dict(), "task_id": None}
        if not resolution.available or not resolution.worker_task_type:
            self.graph.update_status(step.goal_id, "blocked")
            self.graph.update_status(root.goal_id, "blocked")
            return {"status": "blocked", "goal_created": True, "goal_id": root.goal_id,
                    "step_id": step.goal_id, "resolution": resolution.to_dict(), "task_id": None}

        payload = {
            "goal_id": root.goal_id, "goal_step_id": step.goal_id, "request": request,
            "capability": resolution.capability, "command_key": resolution.command_key,
            "autonomy_level": "train_candidates",
            "worker_task_type": resolution.worker_task_type, "attempt": 1, "max_attempts": 3,
        }
        task = self.queue.enqueue(resolution.worker_task_type, payload=payload, priority=15)
        self.graph.update_status(root.goal_id, "queued")
        self.graph.update_status(step.goal_id, "queued")
        return {"status": "queued", "goal_created": True, "goal_id": root.goal_id,
                "step_id": step.goal_id, "resolution": resolution.to_dict(), "task_id": task.id}

    def record_task_result(self, payload: dict[str, Any], result: dict[str, Any]) -> None:
        step_id = str(payload.get("goal_step_id") or "")
        root_id = str(payload.get("goal_id") or "")
        if not step_id or not root_id:
            return
        status = str(result.get("status") or "error")
        if status in {"ok", "completed", "candidate_created", "no_evidence"}:
            self.graph.update_status(step_id, "completed")
            self.graph.update_status(root_id, "completed")
        elif status == "blocked":
            self.graph.update_status(step_id, "blocked")
            self.graph.update_status(root_id, "blocked")
        else:
            attempt = int(payload.get("attempt") or 1)
            max_attempts = max(1, min(int(payload.get("max_attempts") or 3), 5))
            if attempt < max_attempts:
                retry_payload = {**payload, "attempt": attempt + 1, "max_attempts": max_attempts,
                                 "replanned_after": str(result.get("error") or result.get("reason") or "unknown")[:300]}
                retry = self.queue.enqueue(str(payload.get("worker_task_type") or "goal_safe_command"),
                                           payload=retry_payload, priority=min(90, 15 + attempt * 10))
                self.graph.update_status(step_id, "queued")
                self.graph.update_status(root_id, "queued")
                return
            self.graph.update_status(step_id, "failed")
            self.graph.update_status(root_id, "failed")

    def approve_install(self, goal_id: str, package: str, *, approved_by: str) -> dict[str, Any]:
        goal = self.graph.get_goal(goal_id)
        if goal is None or goal.status != "awaiting_approval":
            return {"status": "blocked", "reason": "goal_not_awaiting_approval"}
        children = self.graph.get_children(goal_id)
        if not children:
            return {"status": "blocked", "reason": "goal_step_missing"}
        step = children[0]
        task = self.queue.enqueue("goal_install", payload={"goal_id": goal_id, "goal_step_id": step.goal_id,
            "worker_task_type": "goal_install", "package": package, "human_approved": True,
            "approved_by": approved_by, "attempt": 1, "max_attempts": 1}, priority=5)
        self.graph.update_status(step.goal_id, "queued"); self.graph.update_status(goal_id, "queued")
        return {"status": "queued", "task_id": task.id, "goal_id": goal_id}

    def schedule_lora(self, *, dataset_path: str, approved_by: str, base_model: str = "Qwen/Qwen2.5-0.5B-Instruct",
                      max_steps: int = 20) -> dict[str, Any]:
        root = self.graph.create_goal("Entrenar adaptador LoRA gobernado", dataset_path, priority=1,
                                     metadata={"human_approved_by": approved_by, "budget": {"max_attempts": 1}})
        step = self.graph.create_goal("Entrenamiento y evaluación canary", base_model, parent_id=root.goal_id, priority=1)
        task = self.queue.enqueue("goal_lora_train", payload={"goal_id": root.goal_id, "goal_step_id": step.goal_id,
            "worker_task_type": "goal_lora_train", "dataset_path": dataset_path, "base_model": base_model,
            "max_steps": max_steps, "human_approved": True, "approved_by": approved_by,
            "attempt": 1, "max_attempts": 1}, priority=5)
        self.graph.update_status(step.goal_id, "queued"); self.graph.update_status(root.goal_id, "queued")
        return {"status": "queued", "goal_id": root.goal_id, "task_id": task.id}

    def status(self, goal_id: str) -> dict[str, Any]:
        goal = self.graph.get_goal(goal_id)
        if goal is None:
            return {"status": "not_found", "goal_id": goal_id}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, task_type, status, result_json, error, created_at, started_at, finished_at FROM worker_tasks "
                "WHERE json_extract(payload_json, '$.goal_id')=? ORDER BY id",
                (goal_id,),
            ).fetchall()
        tasks = []
        for row in rows:
            item = dict(row)
            try:
                item["result"] = json.loads(item.pop("result_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                item["result"] = {}
            tasks.append(item)
        return {"status": "ok", "goal": goal.to_dict(),
                "steps": [child.to_dict() for child in self.graph.get_children(goal_id)],
                "tasks": tasks}
