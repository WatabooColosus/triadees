"""Contrato arquitectónico canónico de los Living Workers.

Este módulo no ejecuta ni planifica tareas. Compone las declaraciones que ya
gobiernan el runtime y añade las relaciones que antes sólo podían inferirse al
leer el código: productor, handler, idempotencia, evidencia y reintentos.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from triade.constitution.autonomy import TASK_OPERATION, classify_operation
from triade.runtime.task_status import TERMINAL

from .adaptive_scheduler import AdaptiveScheduler
from .concurrency import TASK_CONCURRENCY_POLICY
from .contracts import WORKER_TASK_TYPES


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int
    max_dispatch_deferrals: int
    backoff: str
    base_delay_seconds: int
    dead_letter_on_exhaustion: bool = True


@dataclass(frozen=True, slots=True)
class WorkerTaskContract:
    task_type: str
    producer: str
    operation: str
    autonomy_level: str
    risk: str
    concurrency_lane: str
    exclusive_key: tuple[str, ...]
    handler: str
    terminal_states: tuple[str, ...]
    cooldown: float
    idempotency: str
    evidence: tuple[str, ...]
    timeout: float
    retry_policy: RetryPolicy

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


TASK_PRODUCERS: dict[str, str] = {
    **{task_type: "MissionPlanner" for task_type in WORKER_TASK_TYPES},
    "learning_candidate_generation": "triade.learning.post_run.schedule_post_run_learning",
    "goal_research": "GoalOrchestrator",
    "goal_safe_command": "GoalOrchestrator",
    "goal_install": "GoalOrchestrator.approve_install",
    "goal_lora_train": "GoalOrchestrator.approve_lora_training",
    "write_governed_text_artifact": "GoalOrchestrator",
}

TASK_HANDLERS: dict[str, str] = {
    task_type: f"_{task_type}" for task_type in WORKER_TASK_TYPES
}


def _contract(task_type: str) -> WorkerTaskContract:
    policy = TASK_CONCURRENCY_POLICY[task_type]
    operation = TASK_OPERATION[task_type]
    return WorkerTaskContract(
        task_type=task_type,
        producer=TASK_PRODUCERS[task_type],
        operation=operation,
        autonomy_level=classify_operation(operation).value,
        risk=policy.resource_class,
        concurrency_lane=policy.lane,
        exclusive_key=policy.exclusive_keys,
        handler=TASK_HANDLERS[task_type],
        terminal_states=tuple(sorted(TERMINAL)),
        cooldown=float(AdaptiveScheduler.DEFAULT_INTERVALS.get(task_type, 60.0)),
        idempotency="idempotency_key plus active payload-hash deduplication",
        evidence=(
            "ExecutionResult.evidence",
            "verified EffectReceipt",
            "task artifacts",
        ),
        timeout=30.0,
        retry_policy=RetryPolicy(
            max_attempts=3,
            max_dispatch_deferrals=20,
            backoff="exponential",
            base_delay_seconds=30,
        ),
    )


WORKER_TASK_CONTRACTS: dict[str, WorkerTaskContract] = {
    task_type: _contract(task_type) for task_type in WORKER_TASK_TYPES
}


def contract_for(task_type: str) -> WorkerTaskContract:
    """Devuelve el contrato declarado; lo desconocido falla cerrado."""
    try:
        return WORKER_TASK_CONTRACTS[task_type]
    except KeyError as exc:
        raise ValueError(f"unknown_worker_task_type:{task_type}") from exc
