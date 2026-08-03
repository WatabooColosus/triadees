"""Contratos de Triade Living Workers."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, get_args
from uuid import uuid4

from triade.core.contracts import utc_now
from triade.runtime.task_status import TERMINAL

from .concurrency import ConcurrencySettings


def _concurrency_enabled_default() -> bool:
    """Concurrencia gobernada **encendida** por defecto desde 2026-08-01.

    Estuvo apagada porque al activarla `test_worker_learning_integration` se
    ponía rojo en CI y el fallo no se reprodujo localmente. Eso ya no describe
    la realidad: en los seis trabajos concurrentes de la matriz (py3.11 ×3 y
    py3.12 ×3) el paso de pytest termina al 100 %, ese test incluido. El rojo
    que se le atribuía venía de otro paso, con una comprobación que exigía datos
    reales de producción en un runner limpio — imposible de cumplir allí, y ya
    corregida.

    Se apaga con `TRIADE_WORKER_CONCURRENCY=0`. Ese interruptor es la vuelta
    atrás: una variable de entorno, sin desplegar código.
    """
    return os.getenv("TRIADE_WORKER_CONCURRENCY", "1").strip().lower() in {
        "1",
        "true",
        "yes",
    }


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
    # La educación prepara lecciones; la evaluación somete una candidata a
    # sandbox, medición y gates. Son etapas distintas del mismo grafo y por eso
    # no comparten tipo de tarea.
    "self_improvement_evaluation",
    # El canary no se observa dentro de la evaluación: acumula observaciones
    # reales entre ciclos del worker, en tareas posteriores e idempotentes.
    "self_improvement_canary_observation",
    # El canary PEFT se observaba sólo desde `scripts/run_phase_13_lora_canary.py`.
    # La única versión inscrita llevaba desde el 2026-07-29 en `canary` al 5 % con
    # una sola observación: ni graduaba ni revertía, exactamente el mismo agujero
    # que tenía el canary de automejora antes de tener productor.
    "peft_canary_observation",
    # El aprendizaje productivo: extraer, deduplicar y medir. Cada etapa es un
    # tipo distinto porque tienen carril, coste y exclusividad distintos.
    "learning_candidate_generation",
    "learning_candidate_deduplication",
    "learning_evidence_generation",
]

#: Se deriva del `Literal`, no se reescribe. Las dos listas se venían
#: manteniendo a mano en paralelo —24 entradas cada una, idénticas por ahora—,
#: y eso sólo aguanta hasta que alguien añada un tipo de tarea en una y se
#: olvide de la otra. Entonces el tipo existiría para el validador y no para el
#: registro, o al revés.
WORKER_TASK_TYPES: tuple[str, ...] = get_args(WorkerTaskType)

# Era `{"completed", "failed", "blocked", "skipped"}`: dejaba fuera `observed`,
# `dead_letter`, `timeout`, `lease_lost`, `dry_run` y `cancelled`. Sólo los dos
# primeros son 327 filas en produccion —el 7 % de la cola— que se habrian
# contado como si siguieran vivas. No lo hicieron porque este nombre no lo usaba
# nadie, pero estaba puesto para que alguien lo usara.
TERMINAL_TASK_STATUSES = TERMINAL


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
    # Concurrencia gobernada. **Encendida por defecto** desde 2026-08-01, con la
    # evidencia que faltaba: los seis trabajos concurrentes de la matriz
    # (py3.11 ×3, py3.12 ×3) terminan el pytest al 100 %, incluido
    # `test_worker_learning_integration` — el test por el que se apagó. El rojo
    # que se le atribuía era de otro paso y por una comprobación imposible de
    # cumplir en un runner limpio, ya corregida.
    #
    # Los límites siguen siendo los conservadores: 3 tareas a la vez como mucho,
    # y un solo hilo para escritura de memoria y para mutación crítica. Encender
    # la concurrencia no es soltar el freno de mano.
    #
    # Se apaga con `TRIADE_WORKER_CONCURRENCY=0` o `concurrency_enabled=False`.
    # Apagada, el drenaje vuelve a ser el secuencial de siempre, bit a bit.
    concurrency_enabled: bool = field(default_factory=_concurrency_enabled_default)
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
