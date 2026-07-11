"""Triade Living Workers: ciclos persistentes, seguros y auditables.

La API pública del paquete expone una política explícita para tareas locales que
pueden ejecutarse sin Ollama Blood. No se modifica ninguna clase durante el
import; la capacidad se declara mediante herencia y permanece inspeccionable.
"""

from .background_service import WorkerBackgroundService
from .scheduler import WorkerScheduler
from .state_store import WorkerStateStore
from .worker_loop import WorkerLoop as _WorkerLoop


class WorkerLoop(_WorkerLoop):
    """WorkerLoop público con capacidades degradadas declaradas explícitamente."""

    READ_ONLY_TASKS_WITHOUT_BLOOD = frozenset(
        {
            *_WorkerLoop.READ_ONLY_TASKS_WITHOUT_BLOOD,
            "pending_learning_review",
        }
    )


__all__ = ["WorkerBackgroundService", "WorkerScheduler", "WorkerStateStore", "WorkerLoop"]
