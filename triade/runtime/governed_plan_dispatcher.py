"""Dispatch Central plan steps to the canonical autonomous queue."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from triade.capabilities.policy import CapabilityPolicyGuard
from triade.core.capability_resolver import CapabilityResolver
from triade.core.central import Central, PlanGraph, PlanStep
from triade.core.contracts import utc_now
from triade.runtime.task_leases import AutonomousTaskStore


@dataclass(frozen=True, slots=True)
class DispatchReceipt:
    plan_id: str
    step_id: str
    task_id: str | None
    capability_id: str
    policy_decision_id: str
    payload_hash: str
    status: str
    created_at: str
    approval_required: bool
    rollback_available: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GovernedPlanDispatcher:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.resolver = CapabilityResolver()
        self.policy = CapabilityPolicyGuard(self.db_path)
        self.tasks = AutonomousTaskStore(self.db_path)
        migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/015_plan_dispatch.sql"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))

    def dispatch(self, graph: PlanGraph, step: PlanStep) -> DispatchReceipt:
        resolution = self.resolver.resolve(step.description)
        capability_id = resolution.capability
        dispatch_payload = dict(step.result.get("dispatch_payload") or {})
        payload = {
            "plan_id": graph.plan_id,
            "plan_step_id": step.id,
            "request": step.description,
            "capability": capability_id,
            "command_key": resolution.command_key,
            **dispatch_payload,
        }
        payload_hash = self.tasks.payload_hash(payload)
        if not resolution.requires_human_approval and (
            not resolution.available or not resolution.worker_task_type
        ):
            return self._blocked(
                graph, step, capability_id, payload_hash, resolution.reason
            )
        decision = self.policy.decide(capability_id, "execute")
        decision_id = self._decision_id(
            capability_id, decision.allowed, decision.reason
        )
        rollback_available = bool(
            decision.capability and decision.capability.get("rollback_policy")
        )
        if not decision.allowed:
            return self._blocked(
                graph, step, capability_id, payload_hash, decision.reason, decision_id
            )
        if resolution.requires_human_approval:
            step.block("human_approval_required")
            receipt = self._receipt(
                graph,
                step,
                None,
                capability_id,
                decision_id,
                payload_hash,
                "blocked",
                True,
                rollback_available,
            )
            self._save(graph)
            return receipt
        if not step.budget.can_proceed():
            return self._blocked(
                graph,
                step,
                capability_id,
                payload_hash,
                "step_budget_exhausted",
                decision_id,
            )
        if not resolution.worker_task_type:
            return self._blocked(
                graph,
                step,
                capability_id,
                payload_hash,
                "worker_task_type_missing",
                decision_id,
            )
        task = self.tasks.enqueue(
            resolution.worker_task_type,
            payload,
            idempotency_key=f"plan:{graph.plan_id}:step:{step.id}:{payload_hash}",
            priority=step.priority * 10,
            max_attempts=max(1, step.max_retries + 1),
        )
        step.state = "queued"
        step.assigned_to = "governed_runtime"
        step.result = {
            "autonomous_task_id": task["task_id"],
            "dispatch_payload": dispatch_payload,
        }
        graph.status = "queued"
        receipt = self._receipt(
            graph,
            step,
            str(task["task_id"]),
            capability_id,
            decision_id,
            payload_hash,
            "queued",
            False,
            rollback_available,
        )
        self._save(graph)
        return receipt

    def synchronize(self, graph: PlanGraph) -> PlanGraph:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            links = {
                str(row["step_id"]): str(row["task_id"])
                for row in conn.execute(
                    "SELECT step_id,task_id FROM governed_plan_dispatches WHERE plan_id=? AND task_id IS NOT NULL",
                    (graph.plan_id,),
                )
            }
        mapping = {
            "pending": "queued",
            "queued": "queued",
            "recovered": "queued",
            "retry_wait": "queued",
            "deferred": "queued",
            "leased": "leased",
            "running": "running",
            "completed": "completed",
            "failed": "failed",
            "dead_letter": "failed",
            "timeout": "failed",
            "lease_lost": "failed",
            "blocked": "blocked",
            "skipped": "cancelled",
            "dry_run": "cancelled",
            "observed": "cancelled",
            "cancelled": "cancelled",
        }
        for step in graph.steps:
            task_id = links.get(step.id)
            task = self.tasks.get(task_id) if task_id else None
            if task:
                step.state = mapping[str(task["status"])]
                step.result = {**step.result, "autonomous_status": task["status"]}
        terminal = {"completed", "failed", "blocked", "cancelled", "rolled_back"}
        if graph.steps and all(step.state in terminal for step in graph.steps):
            graph.completed_at = utc_now()
            graph.status = (
                "completed"
                if all(s.state == "completed" for s in graph.steps)
                else "failed"
            )
        self._save(graph)
        return graph

    def _blocked(
        self,
        graph: PlanGraph,
        step: PlanStep,
        capability_id: str,
        payload_hash: str,
        reason: str,
        decision_id: str = "not_evaluated",
    ) -> DispatchReceipt:
        step.block(reason)
        graph.status = "blocked"
        receipt = self._receipt(
            graph,
            step,
            None,
            capability_id,
            decision_id,
            payload_hash,
            "blocked",
            "approval" in reason,
            False,
        )
        self._save(graph)
        return receipt

    def _receipt(
        self,
        graph: PlanGraph,
        step: PlanStep,
        task_id: str | None,
        capability_id: str,
        decision_id: str,
        payload_hash: str,
        status: str,
        approval_required: bool,
        rollback_available: bool,
    ) -> DispatchReceipt:
        receipt = DispatchReceipt(
            graph.plan_id,
            step.id,
            task_id,
            capability_id,
            decision_id,
            payload_hash,
            status,
            utc_now(),
            approval_required,
            rollback_available,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO governed_plan_dispatches
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    receipt.plan_id,
                    receipt.step_id,
                    receipt.task_id,
                    receipt.capability_id,
                    receipt.policy_decision_id,
                    receipt.payload_hash,
                    receipt.status,
                    receipt.created_at,
                    int(receipt.approval_required),
                    int(receipt.rollback_available),
                ),
            )
        return receipt

    def _save(self, graph: PlanGraph) -> None:
        central = Central()
        central.init_db(str(self.db_path))
        central.save_plan(graph)

    @staticmethod
    def _decision_id(capability: str, allowed: bool, reason: str) -> str:
        raw = json.dumps([capability, allowed, reason], ensure_ascii=False).encode()
        return f"policy-{hashlib.sha256(raw).hexdigest()[:16]}"
