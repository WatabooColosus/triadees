"""Contratos de Triade Living Workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import uuid4

from triade.core.contracts import utc_now

WorkerTaskType = Literal[
    "pulse_check",
    "pending_learning_review",
    "semantic_memory_governance",
    "neuron_candidate_formation",
    "experimental_neuron_activity",
    "neuron_autopromotion",
    "federation_inbox_review",
    "memory_consolidation_review",
    "stable_consolidation_review",
    "system_debt_scan",
    "bodega_global_review",
]

WORKER_TASK_TYPES: tuple[str, ...] = (
    "pulse_check",
    "pending_learning_review",
    "semantic_memory_governance",
    "neuron_candidate_formation",
    "experimental_neuron_activity",
    "neuron_autopromotion",
    "federation_inbox_review",
    "memory_consolidation_review",
    "stable_consolidation_review",
    "system_debt_scan",
    "bodega_global_review",
)

TERMINAL_TASK_STATUSES = {"completed", "failed", "blocked", "skipped"}


def new_worker_run_id() -> str:
    return f"worker-{utc_now().replace(':', '').replace('+', 'Z')}-{uuid4().hex[:8]}"


@dataclass(slots=True)
class WorkerTask:
    task_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 50
    status: str = "pending"
    id: int | None = None
    safety_status: str | None = None
    run_ref: str | None = None
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    result: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkerRunConfig:
    max_iterations: int = 1
    sleep_seconds: float = 5.0
    task_timeout: float = 30.0
    dry_run: bool = False
    once: bool = True
    daemon: bool = False
    runs_dir: str = "runs/background"
    lock_file: str = ".triade_workers.lock"
    stop_file: str = ".triade_stop"
    enabled_task_types: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
