"""Contratos de Triade Living Workers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import uuid4

from triade.core.contracts import utc_now

from .concurrency import ConcurrencySettings

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
    "goal_research",
    "goal_safe_command",
    "research_curriculum",
    "goal_install",
    "goal_lora_train",
    "encrypted_backup",
    "neuron_education_cycle",
    "write_governed_text_artifact",
    "self_improvement_evaluation",
    "self_improvement_canary_observation",
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
    "goal_research",
    "goal_safe_command",
    "research_curriculum",
    "goal_install",
    "goal_lora_train",
    "encrypted_backup",
    "neuron_education_cycle",
    "write_governed_text_artifact",
    # La educación prepara lecciones; la evaluación somete una candidata a
    # sandbox, medición y gates. Son etapas distintas del mismo grafo y por eso
    # no comparten tipo de tarea.
    "self_improvement_evaluation",
    # El canary no se observa dentro de la evaluación: acumula observaciones
    # reales entre ciclos del worker, en tareas posteriores e idempotentes.
    "self_improvement_canary_observation",
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
    id: int | str | None = None
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
    max_tasks_per_drain: int = 20
    max_seconds_per_drain: float = 2.0
    max_tasks_per_type_per_drain: int = 4
    # Concurrencia gobernada. `concurrency_enabled=False` reproduce exactamente
    # el drenaje secuencial anterior; los límites por carril viven en
    # `triade/workers/concurrency.py` y pueden reducirse por backpressure.
    concurrency_enabled: bool = True
    max_concurrent_tasks: int = 3
    read_only_workers: int = 2
    research_workers: int = 1
    evaluation_workers: int = 1
    memory_write_workers: int = 1
    critical_mutation_workers: int = 1
    # Cuánto se espera, como máximo, a que terminen las tareas en vuelo al parar.
    concurrency_shutdown_seconds: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def concurrency_settings(self) -> ConcurrencySettings:
        """Traduce la configuración del run a los límites del pool."""
        return ConcurrencySettings(
            enabled=bool(self.concurrency_enabled),
            max_concurrent_tasks=int(self.max_concurrent_tasks),
            read_only_workers=int(self.read_only_workers),
            research_workers=int(self.research_workers),
            evaluation_workers=int(self.evaluation_workers),
            memory_write_workers=int(self.memory_write_workers),
            critical_mutation_workers=int(self.critical_mutation_workers),
        )
