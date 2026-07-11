"""Triade Living Workers: ciclos de neuronas persistentes, seguros y auditables."""

from .background_service import WorkerBackgroundService
from .scheduler import WorkerScheduler
from .state_store import WorkerStateStore
from .worker_loop import WorkerLoop

# La revisión de candidatos usa únicamente sandbox local determinista. Puede
# ejecutarse sin Ollama porque conserva rechazo explícito ante riesgo de
# identity_core y no consolida memoria estable.
WorkerLoop.READ_ONLY_TASKS_WITHOUT_BLOOD = {
    *WorkerLoop.READ_ONLY_TASKS_WITHOUT_BLOOD,
    "pending_learning_review",
}

__all__ = ["WorkerBackgroundService", "WorkerScheduler", "WorkerStateStore", "WorkerLoop"]
