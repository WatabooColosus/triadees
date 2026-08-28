"""Orquestador persistente de objetivos y delegación a Living Workers."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.workers.task_queue import WorkerTaskQueue

from .capability_resolver import CapabilityResolver
from .planning_graph import GOAL_ACTIVE_STATES, PlanningGraph


class GoalOrchestrator:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.resolver = CapabilityResolver()
        self.graph = PlanningGraph(self.db_path)
        self.queue = WorkerTaskQueue(self.db_path)

    def accept(
        self, request: str, *, run_id: str, source: str = "chat"
    ) -> dict[str, Any]:
        intent = self.resolver.classify(request)
        if intent.kind == "ambiguous":
            return {
                "status": "needs_clarification",
                "intent": intent.to_dict(),
                "goal_created": False,
            }
        resolution = self.resolver.resolve(request)
        if not resolution.actionable:
            return {
                "status": "not_actionable",
                "resolution": resolution.to_dict(),
                "intent": intent.to_dict(),
                "goal_created": False,
            }

        request_key = self._request_key(request, source)
        duplicate = self.graph.find_active_by_request_key(request_key)
        if duplicate is not None:
            task_id = self._first_task_id(duplicate.goal_id)
            self.graph.record_event(
                duplicate.goal_id,
                event_type="duplicate_rejected",
                actor=f"goal_orchestrator:{source}",
                reason="active_request_key_exists",
                evidence={"duplicate_run_id": run_id, "request_key": request_key},
            )
            return {
                "status": "duplicate",
                "goal_created": False,
                "goal_id": duplicate.goal_id,
                "task_id": task_id,
                "resolution": resolution.to_dict(),
            }

        root = self.graph.create_goal(
            title=request[:120],
            description=request,
            priority=2,
            metadata={
                "run_id": run_id,
                "source": source,
                "capability": resolution.capability,
                "resolution": resolution.to_dict(),
                "intent": intent.to_dict(),
                "request_key": request_key,
                "budget": {"max_attempts": 3, "max_minutes": 30},
            },
        )
        step = self.graph.create_goal(
            title=f"Ejecutar capacidad: {resolution.capability}",
            description=resolution.reason,
            parent_id=root.goal_id,
            priority=1,
            metadata={
                "root_goal_id": root.goal_id,
                "capability": resolution.capability,
            },
        )

        if resolution.requires_human_approval:
            self.graph.transition(
                step.goal_id,
                "awaiting_approval",
                actor="capability_resolver",
                reason=resolution.reason,
                event_type="approval_required",
            )
            self.graph.transition(
                root.goal_id,
                "awaiting_approval",
                actor="capability_resolver",
                reason=resolution.reason,
                event_type="approval_required",
            )
            return {
                "status": "awaiting_approval",
                "goal_created": True,
                "goal_id": root.goal_id,
                "step_id": step.goal_id,
                "resolution": resolution.to_dict(),
                "task_id": None,
            }
        if not resolution.available or not resolution.worker_task_type:
            self.graph.transition(
                step.goal_id,
                "blocked",
                actor="capability_resolver",
                reason=resolution.reason,
                event_type="capability_blocked",
            )
            self.graph.transition(
                root.goal_id,
                "blocked",
                actor="capability_resolver",
                reason=resolution.reason,
                event_type="capability_blocked",
            )
            return {
                "status": "blocked",
                "goal_created": True,
                "goal_id": root.goal_id,
                "step_id": step.goal_id,
                "resolution": resolution.to_dict(),
                "task_id": None,
            }

        payload = {
            "goal_id": root.goal_id,
            "goal_step_id": step.goal_id,
            "request": request,
            "capability": resolution.capability,
            "command_key": resolution.command_key,
            "autonomy_level": "train_candidates",
            "worker_task_type": resolution.worker_task_type,
            "attempt": 1,
            "max_attempts": 3,
            # Constancia de que el gobierno ya se ejerció: si la capacidad
            # hubiera exigido una persona, este código no se alcanza --el goal
            # se detiene arriba en `awaiting_approval`--. La puerta de autonomía
            # del worker lo registra en vez de volver a decidirlo, que serían
            # dos gobiernos con contratos distintos sobre lo mismo.
            "autonomy_precleared": "capability_resolver",
        }
        task = self.queue.enqueue(
            resolution.worker_task_type, payload=payload, priority=15
        )
        evidence = {"task_id": task.id, "task_type": resolution.worker_task_type}
        self.graph.transition(
            root.goal_id,
            "queued",
            actor="goal_orchestrator",
            reason="canonical_task_enqueued",
            event_type="task_enqueued",
            evidence=evidence,
        )
        self.graph.transition(
            step.goal_id,
            "queued",
            actor="goal_orchestrator",
            reason="canonical_task_enqueued",
            event_type="task_enqueued",
            evidence=evidence,
        )
        return {
            "status": "queued",
            "goal_created": True,
            "goal_id": root.goal_id,
            "step_id": step.goal_id,
            "resolution": resolution.to_dict(),
            "task_id": task.id,
        }

    def record_task_result(
        self, payload: dict[str, Any], result: dict[str, Any]
    ) -> None:
        step_id = str(payload.get("goal_step_id") or "")
        root_id = str(payload.get("goal_id") or "")
        if not step_id or not root_id:
            return
        status = str(result.get("status") or "error")
        if status in {"ok", "completed"}:
            self.graph.transition(
                step_id,
                "completed",
                actor="worker_result",
                reason="task_completed",
                event_type="task_result",
                evidence={"result_status": status},
            )
            self.graph.transition(
                root_id,
                "completed",
                actor="worker_result",
                reason="all_steps_completed",
                event_type="goal_closed",
                evidence={"result_status": status},
            )
            self._record_learning_observation(
                root_id,
                payload,
                result,
                disposition="no_learning_signal",
            )
        elif status in {
            "candidate_created",
            "no_evidence",
            "observed",
            "skipped",
            "dry_run",
            "blocked",
        }:
            # `blocked` es terminal: desde ahí un goal sólo puede ir a
            # `archived`. No se reintenta, no se aprueba, no vuelve. Registrar
            # como motivo la palabra «blocked» —el propio estado— convierte esa
            # muerte en indiagnosticable: el 2026-08-27 tres peticiones reales
            # («crea un diagnóstico interno breve… y guárdalo») murieron en 0,77
            # segundos con `reason: "blocked"`, y el motivo verdadero
            # —`target_and_authorized_root_required`— sólo estaba en
            # `autonomous_tasks.last_error`, en otra tabla y sin enlace.
            #
            # El handler ya lo dice; sólo hay que no tirarlo por el camino.
            detalle = str(result.get("reason") or result.get("error") or "").strip()
            motivo = f"{status}:{detalle}" if detalle else status
            evidencia = {"result_status": status}
            if detalle:
                evidencia["blocked_reason"] = detalle
            self.graph.transition(
                step_id,
                "blocked",
                actor="worker_result",
                reason=motivo,
                event_type="task_result",
                evidence=evidencia,
            )
            self.graph.transition(
                root_id,
                "blocked",
                actor="worker_result",
                reason=motivo,
                event_type="goal_closed",
                evidence=evidencia,
            )
            self._record_learning_observation(
                root_id, payload, result, disposition="failure_signal"
            )
        else:
            attempt = int(payload.get("attempt") or 1)
            max_attempts = max(1, min(int(payload.get("max_attempts") or 3), 5))
            if attempt < max_attempts:
                self.graph.transition(
                    step_id,
                    "replanning",
                    actor="goal_orchestrator",
                    reason="retryable_task_failure",
                    event_type="replanned",
                    evidence={"attempt": attempt, "max_attempts": max_attempts},
                )
                self.graph.transition(
                    root_id,
                    "replanning",
                    actor="goal_orchestrator",
                    reason="retryable_task_failure",
                    event_type="replanned",
                    evidence={"attempt": attempt, "max_attempts": max_attempts},
                )
                retry_payload = {
                    **payload,
                    "attempt": attempt + 1,
                    "max_attempts": max_attempts,
                    "replanned_after": str(
                        result.get("error") or result.get("reason") or "unknown"
                    )[:300],
                }
                self.queue.enqueue(
                    str(payload.get("worker_task_type") or "goal_safe_command"),
                    payload=retry_payload,
                    priority=min(90, 15 + attempt * 10),
                )
                self.graph.transition(
                    step_id,
                    "queued",
                    actor="goal_orchestrator",
                    reason="retry_task_enqueued",
                    event_type="task_enqueued",
                )
                self.graph.transition(
                    root_id,
                    "queued",
                    actor="goal_orchestrator",
                    reason="retry_task_enqueued",
                    event_type="task_enqueued",
                )
                return
            self.graph.transition(
                step_id,
                "failed",
                actor="worker_result",
                reason="retry_budget_exhausted",
                event_type="task_result",
                evidence={"result_status": status, "attempt": attempt},
            )
            self.graph.transition(
                root_id,
                "failed",
                actor="worker_result",
                reason="retry_budget_exhausted",
                event_type="goal_closed",
                evidence={"result_status": status, "attempt": attempt},
            )
            self._record_learning_observation(
                root_id, payload, result, disposition="failure_signal"
            )

    def approve_install(
        self, goal_id: str, package: str, *, approved_by: str
    ) -> dict[str, Any]:
        goal = self.graph.get_goal(goal_id)
        if goal is None or goal.status != "awaiting_approval":
            return {"status": "blocked", "reason": "goal_not_awaiting_approval"}
        children = self.graph.get_children(goal_id)
        if not children:
            return {"status": "blocked", "reason": "goal_step_missing"}
        step = children[0]
        task = self.queue.enqueue(
            "goal_install",
            payload={
                "goal_id": goal_id,
                "goal_step_id": step.goal_id,
                "worker_task_type": "goal_install",
                "package": package,
                "human_approved": True,
                "approved_by": approved_by,
                "attempt": 1,
                "max_attempts": 1,
            },
            priority=5,
        )
        self.graph.transition(
            step.goal_id,
            "queued",
            actor=approved_by,
            reason="human_install_approval",
            event_type="approved",
            evidence={"task_id": task.id, "package": package},
        )
        self.graph.transition(
            goal_id,
            "queued",
            actor=approved_by,
            reason="human_install_approval",
            event_type="approved",
            evidence={"task_id": task.id, "package": package},
        )
        return {"status": "queued", "task_id": task.id, "goal_id": goal_id}

    def schedule_lora(
        self,
        *,
        dataset_path: str,
        approved_by: str,
        base_model: str | None = None,
        max_steps: int = 20,
        ood_path: str | None = None,
        forgetting_path: str | None = None,
        maximum_gpu_minutes: float = 30.0,
    ) -> dict[str, Any]:
        from triade.training.governed_lora import default_base_model

        resolved_base_model = str(base_model or "").strip() or default_base_model()
        if not resolved_base_model:
            return {"status": "blocked", "reason": "no_served_model_configured"}
        root = self.graph.create_goal(
            "Entrenar adaptador LoRA gobernado",
            dataset_path,
            priority=1,
            metadata={"human_approved_by": approved_by, "budget": {"max_attempts": 1}},
        )
        step = self.graph.create_goal(
            "Entrenamiento y evaluación canary",
            resolved_base_model,
            parent_id=root.goal_id,
            priority=1,
        )
        task = self.queue.enqueue(
            "goal_lora_train",
            payload={
                "goal_id": root.goal_id,
                "goal_step_id": step.goal_id,
                "worker_task_type": "goal_lora_train",
                "dataset_path": dataset_path,
                "base_model": resolved_base_model,
                "max_steps": max_steps,
                "ood_path": ood_path,
                "forgetting_path": forgetting_path,
                "maximum_gpu_minutes": max(1.0, min(float(maximum_gpu_minutes), 120.0)),
                "human_approved": True,
                "approved_by": approved_by,
                "attempt": 1,
                "max_attempts": 1,
            },
            priority=5,
        )
        self.graph.transition(
            step.goal_id,
            "queued",
            actor=approved_by,
            reason="human_lora_approval",
            event_type="approved",
            evidence={"task_id": task.id},
        )
        self.graph.transition(
            root.goal_id,
            "queued",
            actor=approved_by,
            reason="human_lora_approval",
            event_type="approved",
            evidence={"task_id": task.id},
        )
        return {"status": "queued", "goal_id": root.goal_id, "task_id": task.id}

    def status(self, goal_id: str) -> dict[str, Any]:
        goal = self.graph.get_goal(goal_id)
        if goal is None:
            return {"status": "not_found", "goal_id": goal_id}
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT task_id AS id,task_type,status,result_ref AS result_json,
                last_error AS error,created_at,lease_acquired_at AS started_at,
                updated_at AS finished_at FROM autonomous_tasks
                WHERE json_extract(payload_json, '$.goal_id')=? ORDER BY created_at""",
                (goal_id,),
            ).fetchall()
        tasks = []
        for row in rows:
            item = dict(row)
            if (
                item.get("status") == "completed"
                and item.get("error") == "artifact_publication_pending"
            ):
                item["transition_note"] = item.pop("error")
            try:
                result_ref = str(item.pop("result_json") or "")
                item["result"] = (
                    json.loads(Path(result_ref).read_text(encoding="utf-8"))
                    if result_ref and Path(result_ref).is_file()
                    else {}
                )
            except (json.JSONDecodeError, TypeError, OSError):
                item["result"] = {}
            tasks.append(item)
        return {
            "status": "ok",
            "goal": goal.to_dict(),
            "steps": [child.to_dict() for child in self.graph.get_children(goal_id)],
            "tasks": tasks,
            "events": self.graph.get_events(goal_id),
            "learning_observations": self._learning_observations(goal_id),
        }

    def cancel(self, goal_id: str, *, reason: str, cancelled_by: str) -> dict[str, Any]:
        goal = self.graph.get_goal(goal_id)
        if goal is None:
            return {"status": "not_found", "goal_id": goal_id}
        for child in self.graph.get_children(goal_id):
            if child.status in GOAL_ACTIVE_STATES:
                self.graph.transition(
                    child.goal_id,
                    "cancelled",
                    actor=cancelled_by,
                    reason=reason,
                    event_type="cancelled",
                )
        updated = self.graph.transition(
            goal_id,
            "cancelled",
            actor=cancelled_by,
            reason=reason,
            event_type="cancelled",
        )
        return {"status": updated.status, "goal_id": goal_id}

    def expire(self, goal_id: str, *, reason: str) -> dict[str, Any]:
        goal = self.graph.get_goal(goal_id)
        if goal is None:
            return {"status": "not_found", "goal_id": goal_id}
        for child in self.graph.get_children(goal_id):
            if child.status in GOAL_ACTIVE_STATES:
                self.graph.transition(
                    child.goal_id,
                    "expired",
                    actor="goal_expiry_policy",
                    reason=reason,
                    event_type="expired",
                )
        updated = self.graph.transition(
            goal_id,
            "expired",
            actor="goal_expiry_policy",
            reason=reason,
            event_type="expired",
        )
        return {"status": updated.status, "goal_id": goal_id}

    @staticmethod
    def _request_key(request: str, source: str) -> str:
        normalized = unicodedata.normalize("NFKC", request).casefold()
        normalized = " ".join(normalized.split())
        return hashlib.sha256(f"{source}:{normalized}".encode()).hexdigest()

    def _first_task_id(self, goal_id: str) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT task_id FROM autonomous_tasks
                WHERE json_extract(payload_json, '$.goal_id')=?
                ORDER BY created_at,task_id LIMIT 1""",
                (goal_id,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def _record_learning_observation(
        self,
        goal_id: str,
        payload: dict[str, Any],
        result: dict[str, Any],
        *,
        disposition: str,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO goal_learning_observations
                (observation_id,goal_id,task_id,disposition,outcome_status,evidence_json,created_at)
                VALUES(?,?,?,?,?,?,datetime('now'))""",
                (
                    f"goal-learning-{uuid.uuid4().hex[:16]}",
                    goal_id,
                    str(payload.get("task_id") or "") or None,
                    disposition,
                    str(result.get("status") or "error"),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                ),
            )

    def _learning_observations(self, goal_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM goal_learning_observations
                WHERE goal_id=? ORDER BY created_at,observation_id""",
                (goal_id,),
            ).fetchall()
        observations = []
        for row in rows:
            item = dict(row)
            try:
                item["evidence"] = json.loads(str(item.pop("evidence_json") or "{}"))
            except (json.JSONDecodeError, TypeError):
                item["evidence"] = {}
            observations.append(item)
        return observations
