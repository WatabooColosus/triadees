"""Loop controlado de Triade Living Workers."""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from triade.constitution.autonomy import authorize_task
from triade.core.background_neurons import candidates_from_system_debt
from triade.core.contracts import (
    MemoryPacket,
    PlanPacket,
    SignalPacket,
    utc_now,
)
from triade.core.crystal import Crystal
from triade.core.error_bus import record_internal_error
from triade.core.experimental_neuron_runtime import run_experimental_neurons
from triade.core.guarded_web import TRUSTED_RESEARCH_HOSTS
from triade.core.neuron_activity_store import NeuronActivityStore
from triade.core.neuron_autopromoter import NeuronAutopromoter
from triade.core.neuron_formation_pipeline import form_candidates
from triade.core.ollama_blood import check_ollama_blood, ollama_blood_policy
from triade.core.orchestrator_coord import OrchestratorCoordinator
from triade.core.safety import Safety
from triade.db import sqlite3
from triade.federation.federation import Federation
from triade.learning.pipeline import LearningPipeline
from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_store import SemanticMemoryStore
from triade.qualia.bus import QualiaBus
from triade.qualia.contracts import NeuronExperience
from triade.runtime.atomic_completion import AtomicCompletionCoordinator
from triade.runtime.backpressure import QueueDrainBudget, RuntimeBackpressure
from triade.runtime.cancellation import CancellationToken
from triade.runtime.effect_receipt import EffectReceipt
from triade.runtime.event_scheduler import EventDrivenScheduler
from triade.runtime.execution_result import ExecutionResult
from triade.runtime.governed_task_executor import GovernedTaskExecutor
from triade.runtime.lease_heartbeat import LeaseHeartbeat
from triade.runtime.legacy_task_reconciler import LegacyTaskReconciler
from triade.runtime.live_heartbeat import LiveHeartbeat
from triade.runtime.process_lock import RuntimeProcessLock
from triade.runtime.resource_ledger import ResourceLedger, ResourceMeasurementCollector
from triade.runtime.task_artifacts import CanonicalTaskArtifacts
from triade.runtime.task_leases import AutonomousTaskStore
from triade.runtime.task_status import TERMINAL_FAILURE
from triade.runtime.wake_bus import runtime_wake_event

from .adaptive_scheduler import AdaptiveScheduler
from .concurrency import GovernedTaskPool, policy_for
from .contracts import (
    EVENT_DRIVEN_TASK_TYPES,
    WORKER_TASK_TYPES,
    WorkerRunConfig,
    WorkerTask,
    new_worker_run_id,
    timeout_for_attempt,
)
from .neuron_mission_executor import NeuronMissionExecutor
from .scheduler import WorkerScheduler
from .state_store import WorkerStateStore
from .task_queue import WorkerTaskQueue

#: `summary` es el único estado en memoria que varias tareas mutan a la vez, y
#: `+=` sobre un dict no es atómico en CPython.
#:
#: El lock vive a nivel de módulo, no en `WorkerLoop`, y no por gusto:
#: `GovernedTaskExecutor` ejecuta cada handler en un proceso `spawn` aparte para
#: poder imponer el timeout, lo que obliga a **picklear el método enlazado** y con
#: él la instancia entera. Un `threading.Lock` como atributo la haría impicklable
#: y rompería la ejecución de todas las tareas. La contención es irrelevante: se
#: sostiene durante un par de incrementos.
_SUMMARY_LOCK = threading.Lock()


def _auto_approval_enabled() -> bool:
    """¿Puede la política aprobar propuestas sin firma humana? **Sí, por defecto.**

    Esto estaba en `0`, y era el gate en el sitio equivocado. Proponer una mejora
    es reversible: la propuesta solo abre la puerta a investigar, construir una
    candidata y medirla en sandbox. Nada de eso cambia el organismo. Exigir una
    persona ahí no añadía seguridad —el gate de salida sigue igual de duro— pero
    dejaba el circuito de aprendizaje **inerte esperando a alguien**, y convertía
    la aprobación en un trámite que se firma sin mirar.

    El gate se ha movido a donde importa: `stable_promotion_gate`, en el paso
    experimental → estable, que es el irreversible y que hasta ahora **no pedía
    permiso a nadie**.

    Sigue apagable con `TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE=0`. Cuando aprueba
    la política, se registra como `auto:threshold_policy`, nunca como humana.
    """
    return os.getenv(
        "TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE", "1"
    ).strip().lower() not in {"0", "false", "no"}


WORKER_OPERATION_ERRORS = (
    OSError,
    ImportError,
    sqlite3.Error,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    TimeoutError,
)


def _integer_task_id(value: int | str | None) -> int | None:
    return value if isinstance(value, int) else None


class WorkerSandbox:
    """Sandbox local: tareas internas conocidas, sin shell ni red."""

    ALLOWED_TASKS: ClassVar[set[str]] = {
        "validate_learning_candidate",
        "analyze_memory_candidate",
        "json_validation",
        "internal_diagnostic",
    }

    def __init__(self, artifact_dir: str | Path) -> None:
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self, task: str, payload: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        if task not in self.ALLOWED_TASKS:
            return {
                "status": "blocked",
                "task": task,
                "reason": "sandbox_task_not_allowed",
            }
        started = time.monotonic()
        result: dict[str, Any] = {
            "status": "ok",
            "task": task,
            "network": False,
            "shell": False,
        }
        try:
            if task == "validate_learning_candidate":
                content = str(payload.get("content") or "")
                result.update(
                    {
                        "content_length": len(content),
                        "has_source_ref": bool(payload.get("source_ref")),
                        "identity_red_flag": any(
                            flag in content.lower()
                            for flag in (
                                "modificar identidad",
                                "borrar memoria",
                                "identity_core",
                            )
                        ),
                    }
                )
            elif task == "analyze_memory_candidate":
                result.update(
                    {
                        "stable_write": False,
                        "candidate_only": True,
                        "source_ref": payload.get("source_ref"),
                    }
                )
            elif task == "json_validation":
                json.dumps(payload)
                result["valid_json"] = True
            else:
                result["diagnostic"] = "completed"
        except (TypeError, ValueError) as exc:
            result = {"status": "error", "task": task, "error": str(exc)}
        result["elapsed"] = round(time.monotonic() - started, 4)
        if result["elapsed"] > timeout:
            result = {"status": "timeout", "task": task, "timeout": timeout}
        (
            self.artifact_dir / f"sandbox-{task}-{int(time.time() * 1000)}.json"
        ).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result


#: Estados de los que sí se aprende (F-018, aprobado el 2026-08-03). Un
#: `completed` no enseña nada; un fallo, un bloqueo o un gate bajo sí. Se
#: excluye `skipped` porque suele ser trámite y no incidente.
_STATUSES_WORTH_LEARNING = frozenset(
    {"failed", "timeout", "dead_letter", "lease_lost", "blocked", "cancelled"}
)


class WorkerLoop:
    READ_ONLY_TASKS_WITHOUT_BLOOD = frozenset(
        {
            "pulse_check",
            "pending_learning_review",
            "semantic_memory_governance",
            "federation_inbox_review",
            "bodega_global_review",
            "encrypted_backup",
        }
    )
    TASKS_WITHOUT_BLOOD = READ_ONLY_TASKS_WITHOUT_BLOOD | {
        "write_governed_text_artifact",
        # El resolver sólo permite claves de Safe Shell (`git status`, pytest,
        # build). Ninguna usa un modelo. Bloquearlas por falta de Ollama hacía
        # que un diagnóstico válido quedara en `blocked` en runners limpios,
        # antes incluso de alcanzar el handler y su whitelist.
        "goal_safe_command",
        "learning_candidate_generation",
        "learning_candidate_deduplication",
        "neural_learning_distribution",
        "neuron_education_cycle",
    }
    # Estas tareas representan un evento concreto y traen una clave de
    # idempotencia propia. El cooldown sirve para trabajo periódico, no para
    # descartar la segunda conversación porque otra persona habló hace poco.

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        runs_dir: str | Path = "runs/background",
        lock_file: str | Path = ".triade_workers.lock",
        stop_file: str | Path = ".triade_stop",
    ) -> None:
        self.db_path = Path(db_path)
        self.runs_dir = Path(runs_dir)
        self.lock_file = Path(lock_file)
        self.stop_file = Path(stop_file)
        self.store = WorkerStateStore(db_path=self.db_path)
        self.queue = WorkerTaskQueue(db_path=self.db_path)
        self.scheduler = WorkerScheduler(db_path=self.db_path)
        self.adaptive_scheduler = AdaptiveScheduler(db_path=self.db_path)
        self.resource_ledger = ResourceLedger(db_path=self.db_path)
        self.backpressure = RuntimeBackpressure(
            self.resource_ledger, disk_path=self.runs_dir
        )
        self.autonomous_tasks = AutonomousTaskStore(db_path=self.db_path)
        self.task_executor = GovernedTaskExecutor(
            quarantine_root=self.runs_dir / "quarantine" / "timeouts"
        )
        self.live_heartbeat = LiveHeartbeat(db_path=self.db_path)
        self.legacy_reconciler = LegacyTaskReconciler(self.db_path)
        # Se activa solo si el run termina con tareas todavia vivas.
        self._retain_lock_for_active_tasks = False

    def _stamp_lock_owner(self, run_ref: str) -> None:
        """Escribe en el lock a qué run pertenece la autoridad.

        Sólo se sella si el fichero sigue siendo nuestro (mismo PID). Si otro lo
        recuperó entre medias, reescribirlo sería robarle la autoridad — que es
        exactamente lo que este contrato existe para impedir.
        """
        try:
            current = json.loads(self.lock_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(current, dict) or current.get("pid") != os.getpid():
            return
        try:
            self.lock_file.write_bytes(RuntimeProcessLock.payload(run_ref=run_ref))
        except OSError:
            return

    def run(self, config: WorkerRunConfig | None = None) -> dict[str, Any]:
        config = config or WorkerRunConfig(
            runs_dir=str(self.runs_dir),
            lock_file=str(self.lock_file),
            stop_file=str(self.stop_file),
        )
        self.runs_dir = Path(config.runs_dir)
        self.task_executor = GovernedTaskExecutor(
            quarantine_root=self.runs_dir / "quarantine" / "timeouts"
        )
        self.lock_file = Path(config.lock_file)
        self.stop_file = Path(config.stop_file)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.stop_file.parent.mkdir(parents=True, exist_ok=True)
        if self.stop_file.exists():
            return {
                "status": "stopped",
                "stop_file": str(self.stop_file),
                "message": "Stop file presente antes de iniciar.",
            }

        recovery = self.store.recover_interrupted_runtime(self.lock_file)
        if recovery.get("status") == "live_owner":
            return {
                "status": "locked",
                "lock_file": str(self.lock_file),
                "pid": recovery.get("pid"),
                "message": "Worker ya está en ejecución.",
            }
        # Atomic lock: O_CREAT|O_EXCL evita carrera TOCTOU entre múltiples instancias.
        try:
            fd = os.open(
                str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
            os.write(fd, RuntimeProcessLock.payload())
            os.close(fd)
        except FileExistsError:
            return {
                "status": "locked",
                "lock_file": str(self.lock_file),
                "message": "Worker ya está en ejecución.",
            }
        run_ref = new_worker_run_id()
        artifact_dir = self._artifact_dir(run_ref)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        blood = check_ollama_blood()
        blood_policy = ollama_blood_policy("worker_cycle", blood)
        from triade.services.event_bus import publish_event

        # F-043: hasta aquí el único freno del ciclo era si Ollama respondía.
        # Si el modelo contestaba, el worker trabajaba —con el disco al 99 %, con
        # la RAM agotada o con la máquina térmicamente limitada—. El metabolismo
        # medía todo eso y lo escribía en `metabolic_signals`, pero nadie se lo
        # preguntaba: sus lectores eran rutas HTTP, es decir, un humano.
        #
        # El governor ya decidía esto en el arranque de los workers
        # (`worker_autostart.py:261`), una sola vez. Los recursos cambian durante
        # la sesión; la decisión tiene que tomarse en cada ciclo.
        governor = self._governor_decision(blood, run_ref)
        if governor.get("allowed_mode") == "blocked":
            publish_event(
                "worker_cycle_blocked_by_resources",
                "worker_loop",
                {"reason": governor.get("reason"), "limits": governor.get("limits")},
                severity="warning",
                db_path=self.db_path,
                run_ref=run_ref,
            )
            # El lock se suelta aquí sí o sí. Conservarlo tiene sentido cuando
            # quedan tareas vivas; aquí no ha empezado ninguna, y un lock
            # retenido por falta de disco impediría arrancar también cuando el
            # disco vuelva. Sería cambiar una parada por un bloqueo permanente.
            try:
                self.lock_file.unlink()
            except FileNotFoundError:
                pass
            return {
                "status": "blocked",
                "run_ref": run_ref,
                "reason": "resources_exhausted",
                "governor": governor,
                "message": str(governor.get("reason") or "recursos insuficientes"),
            }

        publish_event(
            "ollama_blood_checked",
            "worker_loop",
            {
                "status": blood.get("status"),
                "blood_pressure_score": blood.get("blood_pressure_score"),
            },
            db_path=self.db_path,
            run_ref=run_ref,
        )
        publish_event(
            "ollama_blood_active"
            if blood_policy.get("allowed") and not blood_policy.get("degraded")
            else "ollama_blood_degraded",
            "worker_loop",
            {
                "status": blood.get("status"),
                "degraded_components": blood.get("degraded_components", []),
            },
            severity="info"
            if blood_policy.get("allowed") and not blood_policy.get("degraded")
            else "warning",
            db_path=self.db_path,
            run_ref=run_ref,
        )
        summary: dict[str, Any] = {
            "run_ref": run_ref,
            "iterations": 0,
            "tasks_completed": 0,
            "tasks_blocked": 0,
            "errors": [],
            "ollama_blood_status": blood.get("status"),
            "model_used": blood.get("reasoning_model"),
            "degraded_mode": bool(blood_policy.get("degraded")),
            "cognitive_blood_active": bool(blood.get("cognitive_blood_active")),
            "runtime_recovery": recovery,
        }
        self.store.create_worker_run(run_ref, config, artifact_dir)
        # El lock se tomó antes de existir `run_ref` —tenía que ser así, o la
        # carrera TOCTOU vuelve—, así que ahora se le sella el dueño. Sin esto,
        # un lock retenido sólo se distingue de uno vivo por si el proceso
        # respira, y en el runtime siempre-activo respira toda la sesión.
        # Se reescribe DESPUÉS de `create_worker_run` para que el run ya exista
        # en la base cuando alguien inspeccione: un run desconocido se respeta,
        # y eso dejaría la autoridad retenida por la razón equivocada.
        self._stamp_lock_owner(run_ref)
        self.store.set_state(
            "workers",
            {
                "status": "running",
                "run_ref": run_ref,
                "started_at": utc_now(),
                "config": config.to_dict(),
            },
        )

        try:
            self.legacy_reconciler.reconcile()
            wake_event = runtime_wake_event(self.db_path)
            live_scheduler = EventDrivenScheduler(wake_event=wake_event)
            # Un único pool por run. Con `concurrency_enabled=False` es `None` y
            # el drenaje vuelve a ser exactamente el secuencial de antes.
            settings = config.concurrency_settings()
            pool = GovernedTaskPool(settings) if settings.enabled else None

            def drain_queue() -> int:
                drained = 0
                budget = QueueDrainBudget(
                    max_tasks=config.max_tasks_per_drain,
                    max_seconds=config.max_seconds_per_drain,
                    per_type=config.max_tasks_per_type_per_drain,
                )
                # Antes de nada, retirar lo que ya terminó en el pool. Es lo que
                # convierte el drenaje en no bloqueante: no se espera a ninguna
                # tarea concreta, se recoge lo que haya acabado.
                self._reap_finished(pool, summary)
                # Los reintentos y tareas recuperadas v2 sobreviven aunque su
                # fila legacy ya no esté pendiente.
                deadline = budget.started + budget.max_seconds
                while not budget.exhausted:
                    # A los tipos excluidos por presupuesto se suman los que
                    # ahora mismo no cabrían por carril lleno: así no se arrienda
                    # algo solo para devolverlo acto seguido, ni se bloquea el
                    # drenaje detrás de un carril saturado pudiendo atender otro.
                    saturated = self._saturated_task_types(pool)
                    leased = self.autonomous_tasks.claim(
                        run_ref,
                        lease_seconds=max(60, int(config.task_timeout * 2)),
                        excluded_task_types=budget.excluded_types | saturated,
                    )
                    if leased is None:
                        if not saturated:
                            break
                        # Puede que sí hubiera trabajo y solo faltara sitio.
                        # Terminar aquí dejaría esas tareas sin correr en modo
                        # `once`, donde no hay un ciclo siguiente.
                        pool_wait = pool
                        if pool_wait is None:
                            break
                        pool_wait.wait_for_slot(0.25)
                        if self._reap_finished(pool_wait, summary) == 0:
                            break
                        continue
                    drained += 1
                    budget.record(str(leased["task_type"]))
                    if not self.backpressure.allows(
                        str(leased["task_type"]),
                        effectful=str(leased["task_type"])
                        not in self.READ_ONLY_TASKS_WITHOUT_BLOOD,
                    ):
                        # No llegó a ejecutarse: el intento no se cuenta.
                        self.autonomous_tasks.defer_unstarted(
                            str(leased["task_id"]),
                            run_ref,
                            int(leased["lease_generation"]),
                            "resource_backpressure",
                        )
                        continue
                    self._dispatch_autonomous_task(
                        leased, run_ref, artifact_dir, config, summary, pool, deadline
                    )
                while not budget.exhausted:
                    task = self.queue.claim_next()
                    if task is None:
                        break
                    drained += 1
                    budget.record(task.task_type)
                    payload = dict(task.payload)
                    payload["_legacy_task_id"] = task.id
                    governed = self.autonomous_tasks.enqueue(
                        task.task_type,
                        payload,
                        idempotency_key=f"legacy-worker-task:{task.id}",
                        priority=task.priority,
                        max_attempts=3,
                    )
                    if not self.store.link_delegated_task(
                        int(_integer_task_id(task.id) or 0), str(governed["task_id"])
                    ):
                        self.store.return_delegation_to_pending(
                            int(_integer_task_id(task.id) or 0),
                            "legacy_v2_link_rejected",
                        )
                        continue
                    leased = self.autonomous_tasks.claim_task(
                        str(governed["task_id"]),
                        run_ref,
                        lease_seconds=max(60, int(config.task_timeout * 2)),
                    )
                    if leased is None:
                        self.store.return_delegation_to_pending(
                            int(_integer_task_id(task.id) or 0), "v2_lease_conflict"
                        )
                        self.store.record_event(
                            "task_lease_conflict",
                            "La tarea no pudo obtener lease v2",
                            run_ref=run_ref,
                            task_id=_integer_task_id(task.id),
                            task_type=task.task_type,
                            status="deferred",
                            payload={"autonomous_task_id": governed.get("task_id")},
                        )
                        continue
                    self._dispatch_autonomous_task(
                        leased, run_ref, artifact_dir, config, summary, pool, deadline
                    )
                self._reap_finished(pool, summary)
                return drained

            def dispatch_cycle() -> dict[str, Any]:
                summary["iterations"] += 1
                scheduled = self.scheduler.schedule_cycle(run_ref, config)
                drained = drain_queue()
                if pool is not None:
                    # Snapshot vivo, no solo al cerrar: si únicamente se
                    # registrara en el shutdown, el observador siempre vería
                    # `running: 0` y no sabría nunca qué estuvo corriendo a la vez.
                    summary["concurrency"] = pool.snapshot(queued=pool.pending_count())
                    summary["concurrency"]["running_tasks"] = [
                        {
                            "task_id": entry.task_id,
                            "task_type": entry.task_type,
                            "lane": entry.lane,
                            "resource_class": entry.resource_class,
                            "thread": entry.thread_name,
                            "lease_generation": entry.lease_generation,
                            "started_at": entry.started_at,
                            "running_seconds": round(time.time() - entry.started_at, 3),
                            "exclusive_keys": sorted(entry.keys),
                        }
                        for entry in pool.registry.running_tasks()
                    ]
                return {"scheduled": len(scheduled), "drained": drained}

            dispatch_interval = max(0.001, float(config.sleep_seconds))
            live_scheduler.add_job(
                "heartbeat",
                self.live_heartbeat.pulse,
                interval_seconds=5.0,
                priority=0,
                jitter_seconds=0.1,
                run_immediately=True,
            )
            live_scheduler.add_job(
                "dispatch",
                dispatch_cycle,
                interval_seconds=dispatch_interval,
                priority=20,
                jitter_seconds=min(1.0, dispatch_interval * 0.05),
                run_immediately=True,
            )

            target_iterations: int | float = int(config.max_iterations)
            if target_iterations <= 0:
                target_iterations = float("inf")
            while summary["iterations"] < target_iterations:
                if self.stop_file.exists():
                    summary["stop_requested"] = True
                    break
                live_scheduler.execute_due()
                if config.once:
                    break
                if summary["iterations"] < target_iterations:
                    # Con tareas en vuelo se espera poco, para volver a recoger
                    # resultados pronto en vez de dormir sobre ellos.
                    idle = pool is None or pool.pending_count() == 0
                    wake_reason = live_scheduler.wait(
                        maximum_seconds=5.0 if idle else 0.5
                    )
                    if wake_reason == "event":
                        drain_queue()
                    elif not idle:
                        self._reap_finished(pool, summary)
            # Parada ordenada. Reportar las tareas vivas NO basta: mientras una
            # tarea corre, este run sigue siendo el dueño de su lease, y declarar
            # el run terminado permitiría que otro worker arrancara sobre la
            # misma base creyendo que no hay nadie. Así que se espera de verdad.
            if pool is not None:
                shutdown_report = pool.shutdown(
                    wait_seconds=float(config.concurrency_shutdown_seconds)
                )
                if shutdown_report.get("still_running"):
                    hard_deadline = time.monotonic() + max(
                        60.0, float(config.task_timeout) * 2
                    )
                    while (
                        pool.registry.running_count()
                        and time.monotonic() < hard_deadline
                    ):
                        pool.wait_for_slot(1.0)
                        self._reap_finished(pool, summary)
                    shutdown_report["still_running"] = pool.registry.running_count()
                    shutdown_report["orphans"] = [
                        {"task_id": entry.task_id, "task_type": entry.task_type}
                        for entry in pool.registry.running_tasks()
                    ]
                summary["concurrency_shutdown"] = shutdown_report
                self._reap_finished(pool, summary)
            summary["live_scheduler"] = live_scheduler.snapshot()
            summary["heartbeat"] = self.live_heartbeat.snapshot()
            summary["autonomous_tasks_governed"] = True
            orphaned = int(
                (summary.get("concurrency_shutdown") or {}).get("still_running") or 0
            )
            status = (
                "completed" if not summary.get("errors") else "completed_with_errors"
            )
            if orphaned:
                # Estado propio: ni "completado" (no lo está) ni "fallido" (no
                # falló). Que se note en el estado, no solo en un campo del
                # summary que nadie mira.
                status = "completed_with_active_tasks"
                self._retain_lock_for_active_tasks = True
            self.store.finish_worker_run(run_ref, status, summary)
            self.store.set_state(
                "workers",
                {
                    "status": status,
                    "last_run_ref": run_ref,
                    "finished_at": utc_now(),
                    "summary": summary,
                },
            )
            (artifact_dir / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return {
                "status": status,
                "run_ref": run_ref,
                "artifact_dir": str(artifact_dir),
                **summary,
            }
        except WORKER_OPERATION_ERRORS as exc:
            record_internal_error(
                "worker_loop.run",
                exc,
                run_id=run_ref,
                payload={
                    "module": __name__,
                    "function": "run",
                    "operation": "worker_loop_main",
                },
                db_path=self.db_path,
            )
            summary["errors"].append(str(exc))
            self.store.finish_worker_run(run_ref, "failed", summary, error=str(exc))
            self.store.set_state(
                "workers",
                {
                    "status": "failed",
                    "last_run_ref": run_ref,
                    "error": str(exc),
                    "finished_at": utc_now(),
                },
            )
            return {
                "status": "failed",
                "run_ref": run_ref,
                "artifact_dir": str(artifact_dir),
                "error": str(exc),
                **summary,
            }
        finally:
            if getattr(self, "_retain_lock_for_active_tasks", False):
                # Se conserva el lock a propósito. Soltarlo con tareas todavía
                # vivas dejaría entrar a otro worker sobre la misma base, que es
                # exactamente la doble ejecución que este runtime existe para
                # impedir. No queda huérfano: `recover_interrupted_runtime`
                # comprueba si el PID sigue vivo y recupera el lock caduco
                # cuando el proceso muera.
                self.store.record_event(
                    "worker_lock_retained",
                    "Lock conservado: quedaban tareas vivas al cerrar el run",
                    run_ref=run_ref,
                    status="observed",
                    payload={"lock_file": str(self.lock_file)},
                )
            else:
                try:
                    self.lock_file.unlink()
                except FileNotFoundError:
                    pass

    def _governor_decision(self, blood: dict[str, Any], run_ref: str) -> dict[str, Any]:
        """Pregunta al governor si este ciclo puede gastar, y lo deja anotado.

        El metabolismo existe para que el sistema consuma sin caerse, pero medía
        sin frenar: `metabolic_signals` tenía un escritor y ningún lector, y el
        worker —el que gasta— no lo consultaba en ninguna línea (F-043). Aquí se
        cierra ese lazo con el governor que ya existía y que sólo se usaba una
        vez, al arrancar los workers.

        Un fallo leyendo recursos no puede parar el trabajo: si no se puede
        medir, se devuelve `unknown` y el ciclo sigue. Frenar por no saber sería
        cambiar una parada de recursos por una parada de sensor.
        """
        try:
            from triade.core.resource_governor import decide_work_mode
            from triade.core.resource_probe import build_resource_probe

            probe = build_resource_probe()
            decision = decide_work_mode(probe, blood, "balanced_background")
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            return {"allowed_mode": "unknown", "reason": f"probe_failed: {exc}"}

        limits = probe.get("limits", {}) if isinstance(probe, dict) else {}
        decision["limits"] = {
            "ram_available_gb": limits.get("ram_available_gb"),
            "disk_free_gb": limits.get("disk_free_gb"),
            "load_1min": (probe.get("cpu") or {}).get("load_1min"),
        }
        # La señal se registra siempre, permita o no: una decisión de recursos
        # que sólo se ve cuando bloquea no se puede auditar después.
        try:
            from triade.metabolism.signals import SignalBus

            SignalBus(self.db_path).emit(
                cycle=0,
                stage="worker_cycle_governor",
                status=str(decision.get("allowed_mode") or "unknown"),
                reason=str(decision.get("reason") or "")[:500],
                need_id=run_ref,
            )
        except (ImportError, TypeError, ValueError, sqlite3.Error):
            pass
        return decision

    def _dispatch_autonomous_task(
        self,
        leased: dict[str, Any],
        run_ref: str,
        artifact_dir: Path,
        config: WorkerRunConfig,
        summary: dict[str, Any],
        pool: GovernedTaskPool | None,
        wait_deadline: float = 0.0,
    ) -> bool:
        """Manda la tarea al pool, o la ejecuta en línea si no hay concurrencia.

        La ejecución sigue siendo la misma función de siempre
        (`_execute_autonomous_task`): aquí solo se decide **dónde** corre. No se
        duplica ni una línea de la lógica de cierre, precisamente para que no
        existan dos sitios capaces de cerrar una tarea.

        Los dos rechazos posibles no son el mismo problema y no se tratan igual:

        - **Falta de sitio** (carril o límite global llenos) es transitorio. Se
          espera un poco a que se libere un hueco, recogiendo mientras lo que
          termine. Diferir aquí rompería el modo `once`, donde no hay un ciclo
          siguiente que recoja lo diferido: la tarea simplemente no correría.
        - **Clave de exclusión tomada** es semántico: otra tarea está mutando esa
          misma candidata. Esperar no ayudaría dentro de este drenaje, así que se
          devuelve a la cola de inmediato.

        En ambos casos, devolver a la cola **no consume intento**: esperar turno
        no es fracasar.
        """
        if pool is None:
            self._execute_autonomous_task(
                leased, run_ref, artifact_dir, config, summary
            )
            return True

        task_id = str(leased["task_id"])
        lease_generation = int(leased["lease_generation"])
        payload = dict(leased.get("payload") or {})

        def _run() -> dict[str, Any]:
            return self._execute_autonomous_task(
                leased, run_ref, artifact_dir, config, summary
            )

        while True:
            decision = pool.submit(
                task_id,
                str(leased["task_type"]),
                payload,
                _run,
                lease_generation=lease_generation,
            )
            if decision.admitted:
                return True
            capacity_bound = decision.reason in {"global_limit", "lane_limit"}
            if not capacity_bound or time.monotonic() >= wait_deadline:
                break
            # Espera a que se libere **algún** hueco, nunca a una tarea concreta.
            pool.wait_for_slot(0.25)
            self._reap_finished(pool, summary)

        self.autonomous_tasks.defer_unstarted(
            task_id,
            run_ref,
            lease_generation,
            f"concurrency:{decision.reason}",
        )
        return False

    @staticmethod
    def _saturated_task_types(pool: GovernedTaskPool | None) -> set[str]:
        """Tipos que ahora mismo no cabrían, para no arrendarlos en vano.

        Es una optimización, no una garantía: entre calcular esto y reclamar, el
        estado puede cambiar. La garantía real la da `RunningTaskRegistry`, que
        comprueba y toma las exclusiones bajo el mismo lock.
        """
        if pool is None:
            return set()
        snapshot = pool.snapshot()
        if int(snapshot["running"]) >= int(snapshot["global_limit"]):
            return set(WORKER_TASK_TYPES)
        full = {
            lane
            for lane, state in snapshot["lanes"].items()
            if int(state["running"]) >= int(state["limit"])
        }
        if not full:
            return set()
        return {
            task_type
            for task_type in WORKER_TASK_TYPES
            if policy_for(task_type).lane in full
        }

    def _reap_finished(
        self, pool: GovernedTaskPool | None, summary: dict[str, Any]
    ) -> int:
        """Retira los futuros terminados y deja constancia de los que reventaron.

        Una excepción que escapa de `_execute_autonomous_task` no puede quedarse
        muda dentro del hilo: la tarea ya se cerró (o no) por su propio camino,
        pero el run debe reflejar que algo falló.
        """
        if pool is None:
            return 0
        finished = pool.collect_finished()
        for task_id, future in finished:
            error = future.exception()
            if error is not None:
                message = f"{type(error).__name__}: {error}"
                with _SUMMARY_LOCK:
                    summary.setdefault("errors", []).append(
                        f"concurrent_task_crashed:{task_id}:{message}"
                    )
                record_internal_error(
                    "worker_loop.concurrent_task",
                    error if isinstance(error, Exception) else message,
                    run_id=str(summary.get("run_ref") or ""),
                    payload={"autonomous_task_id": task_id},
                    db_path=self.db_path,
                )
        return len(finished)

    def _execute_autonomous_task(
        self,
        leased: dict[str, Any],
        run_ref: str,
        artifact_dir: Path,
        config: WorkerRunConfig,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        """Ejecuta una tarea solo después de adquirir su lease v2.

        Puede correr en el hilo principal (modo serial) o en un hilo del pool.
        Todo lo que toca —stores, artefactos, lease— abre su propia conexión
        SQLite dentro del hilo que la usa; no se hereda ninguna del principal.
        """
        autonomous_task_id = str(leased["task_id"])
        lease_generation = int(leased["lease_generation"])
        intento = int(leased.get("attempt") or 1)
        payload = dict(leased.get("payload") or {})
        legacy_id = payload.pop("_legacy_task_id", None)
        canonical_artifacts = CanonicalTaskArtifacts(
            artifact_dir, autonomous_task_id, attempt=intento
        )
        staging_path = canonical_artifacts.staging_path()
        task = WorkerTask(
            # v2 is the only execution identity; legacy_id is mirror metadata.
            id=None,
            task_type=str(leased["task_type"]),
            payload=payload,
            priority=int(leased.get("priority") or 50),
        )
        if not self.autonomous_tasks.start(
            autonomous_task_id, run_ref, lease_generation
        ):
            result: dict[str, Any] = {
                "status": "error",
                "error": "autonomous_lease_lost",
            }
        else:
            # El lease se dimensiona sobre el plazo REAL de este intento, no
            # sobre el base: si el timeout escala a 120 s y el lease siguiera
            # valiendo 60, `recover_expired` daría la tarea por perdida mientras
            # todavía se está ejecutando, y otro worker la tomaría en paralelo.
            plazo = timeout_for_attempt(config.task_timeout, intento)
            heartbeat = LeaseHeartbeat(
                self.autonomous_tasks,
                autonomous_task_id,
                run_ref,
                lease_generation,
                max(60, int(plazo * 2)),
            )
            result = self._execute_task(
                task,
                run_ref,
                artifact_dir,
                config,
                lease_heartbeat=heartbeat,
                task_artifact_dir=staging_path,
                attempt=intento,
            )
        provisional_ref = str(staging_path / "result.json")
        result = self._remap_artifact_paths(
            result, str(staging_path), str(canonical_artifacts.path)
        )
        try:
            execution = self._canonical_execution_result(result, provisional_ref)
        except ValueError as exc:
            execution = ExecutionResult(
                status="failed",
                executed=True,
                retryable=False,
                error_code="unknown_handler_status",
                message=str(exc),
                artifacts=[provisional_ref] if Path(provisional_ref).exists() else [],
                evidence=[provisional_ref] if Path(provisional_ref).exists() else [],
            )
            result = {
                **result,
                "status": "error",
                "error": str(exc),
                "error_code": "unknown_handler_status",
            }

        final_result_ref = str(canonical_artifacts.path / "result.json")
        execution.artifacts = [final_result_ref]
        execution.evidence = [final_result_ref]
        if execution.effect_receipt is not None:
            execution.effect_receipt.evidence_refs = [final_result_ref]
        canonical_artifacts.finalize(
            task=leased,
            execution=execution.model_dump(mode="json"),
            result=result,
            worker_id=run_ref,
            lease_generation=lease_generation,
            payload_hash=str(leased["payload_hash"]),
            status=execution.status,
            target_path=staging_path,
        )
        result_ref = final_result_ref
        if execution.status == "completed":
            transitioned = AtomicCompletionCoordinator(self.autonomous_tasks).complete(
                task_id=autonomous_task_id,
                worker_id=run_ref,
                lease_generation=lease_generation,
                artifacts=canonical_artifacts,
                staging_path=staging_path,
            )
        else:
            try:
                canonical_artifacts.publish(staging_path)
            except OSError:
                transitioned = False
            else:
                transitioned = self._persist_execution_result(
                    autonomous_task_id,
                    run_ref,
                    lease_generation,
                    execution,
                    result_ref,
                )
        if not transitioned:
            execution = ExecutionResult(
                status="lease_lost",
                executed=True,
                retryable=True,
                error_code="terminal_transition_rejected",
                message="El lease dejó de pertenecer al worker antes del cierre",
                artifacts=[result_ref] if Path(result_ref).exists() else [],
                evidence=[],
            )
            result = {
                **result,
                "status": "lease_lost",
                "error": execution.message,
            }

        with _SUMMARY_LOCK:
            if execution.status == "blocked":
                summary["tasks_blocked"] += 1
            elif execution.status in TERMINAL_FAILURE:
                summary["errors"].append(result.get("error") or "task_failed")
            elif execution.status == "completed":
                summary["tasks_completed"] += 1
        result["execution_result"] = execution.model_dump(mode="json")
        if legacy_id is not None:
            canonical = self.autonomous_tasks.get(autonomous_task_id) or {}
            terminal_status = str(canonical.get("status") or "")
            if terminal_status in {
                "completed",
                "blocked",
                "skipped",
                "dry_run",
                "observed",
                "cancelled",
                "failed",
                "dead_letter",
                "timeout",
                "lease_lost",
            }:
                self.store.mirror_v2_terminal(
                    int(legacy_id),
                    autonomous_task_id,
                    terminal_status,
                    result,
                    run_ref=run_ref,
                )
        return result

    @staticmethod
    def _canonical_execution_result(
        result: dict[str, Any], result_ref: str
    ) -> ExecutionResult:
        raw_status = str(result.get("status") or "").strip()
        evidence = [result_ref] if Path(result_ref).exists() else []
        message = str(result.get("reason") or result.get("message") or "")
        resource_usage = dict(result.get("resource_usage") or {})
        if raw_status in {"blocked"}:
            return ExecutionResult(status="blocked", executed=False, message=message)
        if raw_status == "skipped":
            return ExecutionResult(status="skipped", executed=False, message=message)
        if raw_status == "dry_run":
            return ExecutionResult(status="dry_run", executed=False, message=message)
        if raw_status in {
            "observed",
            "no_target",
            "no_evidence",
            "needs_research",
            # GovernedResearchWorker.run() (triade/research/governed.py) --
            # inalcanzable mientras research_curriculum estuvo bloqueado por
            # falta de allowed_sources (corregido 2026-07-30). Al correr de
            # verdad, estos tres estados legitimos empezaron a crashear con
            # "unknown_handler_status" porque nunca se habian agregado aqui
            # (hallazgo en vivo, auditoria 2026-07-31). No son fallos: el
            # research corrio bien y decidio, correctamente, no reclamar
            # evidencia que no tenia.
            "insufficient_sources",
            "conflicting_sources",
            "unverifiable",
        }:
            return ExecutionResult(status="observed", executed=False, message=message)
        if raw_status == "deferred":
            # "Todavía no hay evidencia" no es "esto falló". Tratarlo como fallo
            # descartaría candidatas válidas por haber llegado antes que sus
            # datos, y un canary nunca llegaría a acumular observaciones: cada
            # ciclo sin informes nuevos contaría como intento fallido.
            return ExecutionResult(
                status="deferred",
                executed=False,
                retryable=True,
                error_code=str(result.get("defer_cause") or "deferred"),
                message=message,
                artifacts=evidence,
                evidence=evidence,
                resource_usage=resource_usage,
            )
        if raw_status in {"error", "failed"}:
            return ExecutionResult(
                status="failed",
                executed=True,
                retryable=True,
                error_code=str(result.get("error_code") or "handler_failed"),
                message=str(result.get("error") or message),
                artifacts=evidence,
                evidence=evidence,
                resource_usage=resource_usage,
            )
        if raw_status == "timeout":
            return ExecutionResult(
                status="timeout",
                executed=True,
                retryable=True,
                error_code="task_timeout",
                message=message,
                artifacts=evidence,
                evidence=evidence,
                resource_usage=resource_usage,
            )
        success = {
            "ok",
            "completed",
            "candidate_created",
            "consolidated",
            "lesson_prepared",
        }
        if raw_status not in success:
            raise ValueError(f"unknown_handler_status:{raw_status or '<empty>'}")
        raw_receipt = result.get("effect_receipt")
        effect_applied = raw_status in {
            "candidate_created",
            "consolidated",
            "lesson_prepared",
        } or bool(raw_receipt and str(raw_receipt.get("action") or "") != "observe")
        if raw_receipt:
            receipt = EffectReceipt.model_validate(raw_receipt)
            if not receipt.verified:
                # Un handler que dice «completado» con un recibo sin verificar
                # se contradice a sí mismo. Antes esto llegaba a
                # `ExecutionResult` y reventaba con un `ValueError` que el bucle
                # trata como fallo *reintentable*: el mismo dato producía el
                # mismo recibo tres veces y la tarea acababa en `dead_letter`
                # con un error de validación en vez de una causa. Se devuelve el
                # mismo veredicto que la rama de abajo, y no reintentable porque
                # es determinista.
                return ExecutionResult(
                    status="failed",
                    executed=True,
                    retryable=False,
                    error_code="unverified_effect_receipt",
                    message=(
                        "El handler declaró 'completed' con un recibo sin"
                        f" verificar: {receipt.action} sobre {receipt.target}"
                    ),
                    artifacts=evidence,
                    evidence=evidence,
                    resource_usage=resource_usage,
                )
        elif not effect_applied and evidence:
            receipt = EffectReceipt(
                action="observe",
                target=str(result.get("task_type") or "governed_handler"),
                execution={"handler_status": raw_status},
                postcondition={"passed": True, "result_artifact_exists": True},
                verified=True,
                verifier="result_artifact_verifier",
                evidence_refs=evidence,
            )
        else:
            return ExecutionResult(
                status="failed",
                executed=True,
                retryable=False,
                error_code="verified_effect_receipt_missing",
                message="El handler afirmó un efecto sin recibo verificable",
                artifacts=evidence,
                evidence=evidence,
                resource_usage=resource_usage,
            )
        return ExecutionResult(
            status="completed",
            executed=True,
            effect_applied=effect_applied,
            artifacts=evidence,
            evidence=evidence,
            resource_usage=resource_usage,
            observation_justification=None
            if evidence
            else "pure_observation_without_artifact",
            postconditions={
                "effect_expected": effect_applied,
                "artifact_required": True,
            },
            message=message,
            effect_receipt=receipt,
        )

    def _persist_execution_result(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        execution: ExecutionResult,
        result_ref: str,
    ) -> bool:
        reason = execution.message or execution.error_code or execution.status
        if execution.status == "completed":
            return self.autonomous_tasks.complete(
                task_id, worker_id, lease_generation, result_ref
            )
        if execution.status == "blocked":
            return self.autonomous_tasks.block(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status == "skipped":
            return self.autonomous_tasks.skip(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status == "dry_run":
            return self.autonomous_tasks.mark_dry_run(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status == "observed":
            return self.autonomous_tasks.mark_observed(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status == "cancelled":
            return self.autonomous_tasks.cancel(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status == "deferred":
            return self.autonomous_tasks.defer(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status == "timeout":
            return self.autonomous_tasks.mark_timeout(
                task_id,
                worker_id,
                lease_generation,
                reason,
                retryable=execution.retryable,
            )
        if execution.status == "lease_lost":
            return self.autonomous_tasks.mark_lease_lost(
                task_id, worker_id, lease_generation, reason
            )
        if execution.status in {"failed", "dead_letter"}:
            failed = self.autonomous_tasks.fail(
                task_id, worker_id, lease_generation, reason
            )
            return failed.get("status") != "not_owner"
        raise ValueError(f"unknown_execution_status:{execution.status}")

    def request_stop(self) -> dict[str, Any]:
        self.stop_file.write_text(utc_now(), encoding="utf-8")
        self.store.set_state(
            "workers",
            {
                "status": "stop_requested",
                "stop_file": str(self.stop_file),
                "at": utc_now(),
            },
        )
        return {"status": "stop_requested", "stop_file": str(self.stop_file)}

    def clear_stop(self) -> None:
        try:
            self.stop_file.unlink()
        except FileNotFoundError:
            pass

    def _execute_task(
        self,
        task: WorkerTask,
        run_ref: str,
        artifact_dir: Path,
        config: WorkerRunConfig,
        *,
        lease_heartbeat: LeaseHeartbeat | None = None,
        task_artifact_dir: Path | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        started = time.monotonic()
        resource_collector = ResourceMeasurementCollector()
        cancellation = CancellationToken(lambda: self.stop_file.exists())
        cancellation.checkpoint()
        goal_task = bool(task.payload.get("goal_id"))
        resolution_task = bool(task.payload.get("resolution_ready"))
        if (
            not goal_task
            and not resolution_task
            and task.task_type not in EVENT_DRIVEN_TASK_TYPES
            and self.adaptive_scheduler.should_skip_task(task.task_type)
        ):
            result: dict[str, Any] = {
                "status": "skipped",
                "reason": "adaptive_interval_not_elapsed",
                "task_type": task.task_type,
            }
            self.store.finish_task(
                _integer_task_id(task.id) or 0,
                "skipped",
                result,
                "approved",
                run_ref=run_ref,
            )
            return result
        blood = check_ollama_blood()
        blood_policy = ollama_blood_policy("worker_cycle", blood)
        safety = self._safety_for_task(task, run_ref)
        task_dir = (
            task_artifact_dir or artifact_dir / f"task-{task.id}-{task.task_type}"
        )
        task_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(task.payload, dict):
            task.payload.setdefault("ollama_blood", blood)
        base = {
            "task": task.to_dict(),
            "safety": safety.to_dict(),
            "dry_run": config.dry_run,
            "started_at": utc_now(),
        }
        (task_dir / "input.json").write_text(
            json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if (
            blood_policy.get("degraded")
            and task.task_type not in self.TASKS_WITHOUT_BLOOD
        ):
            result = {
                "status": "blocked",
                "reason": "Ollama Blood no disponible; worker limitado a observe/read-only.",
                "ollama_blood_status": blood.get("status"),
                "model_used": blood.get("reasoning_model"),
                "degraded_mode": True,
                "cognitive_blood_active": False,
            }
            self.store.finish_task(
                _integer_task_id(task.id) or 0,
                "blocked",
                result,
                safety.status,
                run_ref=run_ref,
            )
            self.store.record_event(
                "task_blocked_no_blood",
                result["reason"],
                run_ref=run_ref,
                task_id=_integer_task_id(task.id),
                task_type=task.task_type,
                status="blocked",
                payload=result,
            )
        elif safety.status == "blocked" or safety.human_approval_required:
            result = {
                "status": "blocked",
                "reason": safety.reason,
                "safety_status": safety.status,
            }
            self.store.finish_task(
                _integer_task_id(task.id) or 0,
                "blocked",
                result,
                safety.status,
                run_ref=run_ref,
            )
            self.store.record_event(
                "task_blocked",
                safety.reason,
                run_ref=run_ref,
                task_id=_integer_task_id(task.id),
                task_type=task.task_type,
                status="blocked",
                payload=result,
            )
        elif not (
            autonomy := authorize_task(
                task.task_type, task.payload if isinstance(task.payload, dict) else {}
            )
        ).allowed:
            # El registro de autonomía existía con pruebas y **no gobernaba
            # nada**: contrato sin consumidor, el patrón que esta auditoría
            # persigue. Aquí es donde se consulta.
            #
            # No duplica a Safety: Safety revisa el contenido de la petición,
            # esto revisa si la *operación* puede avanzar sin una persona. Un
            # tipo de tarea sin operación declarada cae aquí por defecto, que es
            # lo que evita que un tipo nuevo herede permisos que nadie le dio.
            result = {
                "status": "blocked",
                "reason": autonomy.reason,
                "autonomy": autonomy.to_dict(),
            }
            self.store.finish_task(
                _integer_task_id(task.id) or 0,
                "blocked",
                result,
                safety.status,
                run_ref=run_ref,
            )
            self.store.record_event(
                "task_blocked_by_autonomy",
                autonomy.reason,
                run_ref=run_ref,
                task_id=_integer_task_id(task.id),
                task_type=task.task_type,
                status="blocked",
                payload=result,
            )
        elif config.dry_run:
            result = {
                "status": "dry_run",
                "task_type": task.task_type,
                "would_execute": True,
            }
            self.store.finish_task(
                _integer_task_id(task.id) or 0,
                "dry_run",
                result,
                safety.status,
                run_ref=run_ref,
            )
        else:
            try:
                handlers: dict[
                    str,
                    Callable[[WorkerTask, str, Path, WorkerRunConfig], dict[str, Any]],
                ] = {
                    "pulse_check": self._pulse_check,
                    "pending_learning_review": self._pending_learning_review,
                    "semantic_memory_governance": self._semantic_memory_governance,
                    "neuron_candidate_formation": self._neuron_candidate_formation,
                    "experimental_neuron_activity": self._experimental_neuron_activity,
                    "neuron_autopromotion": self._neuron_autopromotion,
                    "federation_inbox_review": self._federation_inbox_review,
                    "stable_consolidation_review": self._stable_consolidation_review,
                    "system_debt_scan": self._system_debt_scan,
                    "bodega_global_review": self._bodega_global_review,
                    "goal_research": self._goal_research,
                    "goal_safe_command": self._goal_safe_command,
                    "research_curriculum": self._research_curriculum,
                    "goal_install": self._goal_install,
                    "goal_lora_train": self._goal_lora_train,
                    "encrypted_backup": self._encrypted_backup,
                    "neuron_education_cycle": self._neuron_education_cycle,
                    "write_governed_text_artifact": self._write_governed_text_artifact,
                    "self_improvement_evaluation": self._self_improvement_evaluation,
                    "self_improvement_canary_observation": (
                        self._self_improvement_canary_observation
                    ),
                    "learning_candidate_generation": (
                        self._learning_candidate_generation
                    ),
                    "learning_candidate_deduplication": (
                        self._learning_candidate_deduplication
                    ),
                    "learning_claim_distillation": (self._learning_claim_distillation),
                    "learning_evidence_generation": (
                        self._learning_evidence_generation
                    ),
                    "neural_learning_distribution": (
                        self._neural_learning_distribution
                    ),
                    "peft_canary_observation": self._peft_canary_observation,
                }
                # El plazo crece con el intento: un timeout dice "no le dio
                # tiempo", no "el trabajo está mal". Ver `timeout_for_attempt`.
                plazo = timeout_for_attempt(config.task_timeout, attempt)
                outcome = self.task_executor.execute_callable(
                    handlers[task.task_type],
                    args=(task, run_ref, task_dir, config),
                    timeout_seconds=plazo,
                    artifact_dir=task_dir,
                    heartbeat=lease_heartbeat.renew if lease_heartbeat else None,
                    heartbeat_interval_seconds=(
                        lease_heartbeat.interval_seconds if lease_heartbeat else 15.0
                    ),
                    cancellation_check=lambda: cancellation.cancelled,
                )
                if outcome.status == "timeout":
                    result = {
                        "status": "timeout",
                        "error": outcome.error,
                        "timeout": plazo,
                        "timeout_base": config.task_timeout,
                        "attempt": attempt,
                        "termination_signal": outcome.termination_signal,
                        "quarantine_ref": outcome.quarantine_ref,
                        "stdout_ref": outcome.stdout_ref,
                        "stderr_ref": outcome.stderr_ref,
                    }
                elif outcome.status == "cancelled":
                    result = {"status": "cancelled", "reason": outcome.error}
                elif outcome.status == "lease_lost":
                    result = {
                        "status": "lease_lost",
                        "error": outcome.error,
                        "termination_signal": outcome.termination_signal,
                        "quarantine_ref": outcome.quarantine_ref,
                    }
                elif outcome.status == "failed":
                    result = {
                        "status": "error",
                        "error": outcome.error or "governed_child_failed",
                        "exit_code": outcome.exit_code,
                        "stdout_ref": outcome.stdout_ref,
                        "stderr_ref": outcome.stderr_ref,
                    }
                else:
                    result = outcome.result
                result_status = str(result.get("status") or "")
                if result_status in {
                    "ok",
                    "completed",
                    "candidate_created",
                    "consolidated",
                    "lesson_prepared",
                }:
                    persisted_status = "completed"
                elif result_status in {
                    "observed",
                    "no_target",
                    "no_evidence",
                    "needs_research",
                    # Mismos estados legitimos de GovernedResearchWorker que
                    # _canonical_execution_result -- ver comentario ahi.
                    # Duplicado aqui porque este es un mapeo de estado
                    # separado para tareas v2/delegadas, no el mismo codigo.
                    "insufficient_sources",
                    "conflicting_sources",
                    "unverifiable",
                }:
                    persisted_status = "observed"
                elif result_status in {
                    "blocked",
                    "skipped",
                    "dry_run",
                    "cancelled",
                    "failed",
                    "timeout",
                    "lease_lost",
                }:
                    persisted_status = (
                        "failed" if result_status == "error" else result_status
                    )
                elif result_status == "error":
                    persisted_status = "failed"
                else:
                    raise ValueError(
                        f"unknown_handler_status:{result_status or '<empty>'}"
                    )
                self.store.finish_task(
                    _integer_task_id(task.id) or 0,
                    persisted_status,
                    result,
                    safety.status,
                    run_ref=run_ref,
                )
                self.store.record_event(
                    f"task_{persisted_status}",
                    f"{task.task_type}: {persisted_status}",
                    run_ref=run_ref,
                    task_id=_integer_task_id(task.id),
                    task_type=task.task_type,
                    payload=result,
                )
                if persisted_status in _STATUSES_WORTH_LEARNING:
                    self._learn_from_failure(run_ref, task, persisted_status, result)
                if task.payload.get("goal_id"):
                    from triade.core.goal_orchestrator import GoalOrchestrator

                    GoalOrchestrator(self.db_path).record_task_result(
                        task.payload, result
                    )
            except WORKER_OPERATION_ERRORS as exc:
                record_internal_error(
                    "worker_loop.execute_task",
                    exc,
                    run_id=run_ref,
                    task_id=_integer_task_id(task.id),
                    payload={
                        "module": __name__,
                        "function": "_execute_task",
                        "operation": "execute_worker_task_handler",
                        "task_type": task.task_type,
                    },
                    db_path=self.db_path,
                )
                result = {
                    "status": "error",
                    "task_type": task.task_type,
                    "error": str(exc),
                }
                self.store.finish_task(
                    _integer_task_id(task.id) or 0,
                    "failed",
                    result,
                    safety.status,
                    error=str(exc),
                    run_ref=run_ref,
                )
                self.store.record_event(
                    "task_failed",
                    str(exc),
                    run_ref=run_ref,
                    task_id=_integer_task_id(task.id),
                    task_type=task.task_type,
                    status="error",
                    payload=result,
                )
        result["ollama_blood_status"] = blood.get("status")
        result["model_used"] = blood.get("reasoning_model")
        result["degraded_mode"] = bool(blood_policy.get("degraded"))
        result["cognitive_blood_active"] = bool(blood.get("cognitive_blood_active"))
        result["elapsed"] = round(time.monotonic() - started, 4)
        self.adaptive_scheduler.record_task_execution(
            task.task_type,
            result["elapsed"] * 1000,
            str(result.get("status")) not in {"error", "failed", "blocked"},
            run_ref=run_ref,
        )
        resource_usage = resource_collector.finish()
        result["resource_usage"] = resource_usage.to_dict()
        self.resource_ledger.record_usage(
            task_id=str(task.id) if task.id is not None else None,
            worker_id=run_ref,
            neuron_id=str(
                task.payload.get("neuron_id")
                or task.payload.get("related_neuron_id")
                or ""
            )
            or None,
            usage=resource_usage,
            model=str(result.get("model_used") or "") or None,
            success=str(result.get("status")) not in {"error", "failed", "blocked"},
            task_class=self.adaptive_scheduler.task_class(task.task_type),
        )
        task_dir.mkdir(parents=True, exist_ok=True)
        from triade.runtime.task_artifacts import AtomicArtifactWriter

        AtomicArtifactWriter.write_json(task_dir / "result.json", result)
        return result

    @classmethod
    def _remap_artifact_paths(cls, value: Any, old_prefix: str, new_prefix: str) -> Any:
        if isinstance(value, dict):
            return {
                key: cls._remap_artifact_paths(item, old_prefix, new_prefix)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                cls._remap_artifact_paths(item, old_prefix, new_prefix)
                for item in value
            ]
        if isinstance(value, str) and value.startswith(old_prefix):
            return f"{new_prefix}{value[len(old_prefix) :]}"
        return value

    def _research_curriculum(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Investiga una laguna real; la evidencia queda candidata, nunca estable."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT n.id, n.name, n.domain, COUNT(na.id) AS evidence_count
                   FROM neurons n LEFT JOIN neuron_activity na ON na.neuron_id=n.id
                   WHERE n.status IN ('experimental','candidate','candidate_reviewable')
                   GROUP BY n.id ORDER BY evidence_count ASC, n.id ASC LIMIT 1"""
            ).fetchone()
        if row is None:
            return {"status": "no_evidence", "reason": "no_neuronal_gap"}
        domain_value = str(row["domain"] or "general")
        from triade.neurons.curriculum import domain_query
        from triade.research.governed import (
            REPEATED_FAILURE_THRESHOLD,
            prior_failed_research,
        )

        # El mapa vive en `curriculum.py` y lo comparten investigación y
        # currículo. Duplicarlo aquí era el corte: cada lado buscaba con un
        # vocabulario distinto para la misma neurona.
        clean_domain = domain_query(domain_value)
        clean_name = str(row["name"] or "").replace("neurona-", "").replace("-", " ")
        # El nombre de una neurona nacida de una conversación es la frase que la
        # creó, no un tema: `neurona-como-hace-lindo` metía «como hace lindo» en
        # la consulta y la volvía ruido. Mientras funcione se conserva —acota la
        # búsqueda—, pero si esta misma pregunta ya falló varias veces, insistir
        # con ella es el bucle que dejó 156 runs idénticos. Entonces se reintenta
        # con el dominio solo, que es la parte que sí describe qué se busca.
        pregunta_completa = (
            f"{clean_domain} {clean_name} documentación técnica fundamentos"
        )
        scope = str(task.payload.get("scope") or "goal_research")
        fallos_previos = prior_failed_research(self.db_path, pregunta_completa, scope)
        if fallos_previos >= REPEATED_FAILURE_THRESHOLD:
            pregunta_completa = f"{clean_domain} documentación técnica fundamentos"
        # TRUSTED_RESEARCH_HOSTS (guarded_web.py) es la fuente unica de estos
        # dominios -- sin esto, _goal_research bloqueaba SIEMPRE con
        # "requires explicit allowed_sources" y el currículo autónomo nunca
        # investigaba nada real pese a detectar lagunas neuronales genuinas
        # (hallazgo 2026-07-30, ver TECHNICAL_DEBT.md). No se amplía a
        # búsqueda web sin restricción: sigue acotado a las mismas fuentes ya
        # vetadas. Antes de 2026-07-31 esta lista estaba duplicada aquí en
        # vez de importada -- ver TECHNICAL_DEBT.md.
        delegated = WorkerTask(
            task_type="goal_research",
            payload={
                "request": pregunta_completa,
                "related_neuron_id": int(row["id"]),
                "curriculum": True,
                "allowed_sources": sorted(TRUSTED_RESEARCH_HOSTS),
                "scope": scope,
            },
        )
        result = self._goal_research(delegated, run_ref, task_dir, config)
        result["curriculum_gap"] = dict(row)
        result["prior_failed_attempts"] = fallos_previos
        result["query_narrowed_after_failures"] = (
            fallos_previos >= REPEATED_FAILURE_THRESHOLD
        )
        return result

    def _goal_install(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.training.installer import IsolatedInstaller

        return IsolatedInstaller(self.db_path).install(
            str(task.payload.get("package") or ""),
            goal_id=str(task.payload.get("goal_id") or run_ref),
            approved=bool(task.payload.get("human_approved")),
            approved_by=str(task.payload.get("approved_by") or ""),
        )

    def _goal_lora_train(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.training.governed_lora import GovernedLoraJobRunner

        return GovernedLoraJobRunner(self.db_path).run(task.payload)

    def _encrypted_backup(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.memory.encrypted_backup import EncryptedBackup

        backup = EncryptedBackup(self.db_path)
        created = backup.create()
        if created.get("status") == "blocked":
            return {
                "status": "blocked",
                "reason": created.get("reason", "backup_creation_blocked"),
                "backup": created,
            }
        verified = backup.verify(Path("artifacts/backups") / created["file"])
        if verified.get("status") != "ok":
            return {
                "status": "error",
                "reason": "backup_verification_failed",
                "verification": verified,
            }
        backup_ref = Path("artifacts/backups") / created["file"]
        verification_ref = task_dir / "backup-restore-verification.json"
        verification_ref.write_text(
            json.dumps(verified, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        receipt = EffectReceipt.verify_backup(
            backup_ref=str(backup_ref),
            hash_matches=verified.get("sha256") == created.get("sha256"),
            restore_test_ref=str(verification_ref),
        )
        if not receipt.verified:
            return {
                "status": "error",
                "reason": "backup_effect_receipt_failed",
                "verification": verified,
            }
        return {
            "status": "completed",
            "backup": created,
            "verification": verified,
            "retention": backup.enforce_retention(),
            "restore_drill": backup.run_restore_drill(backup_ref),
            "effect_receipt": receipt.model_dump(mode="json"),
        }

    def _neuron_education_cycle(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.neurons import NeuronEducationCycle
        from triade.neurons.education_applications import (
            NeuronEducationApplicationRecorder,
        )
        from triade.neurons.education_resolver import NeuronEducationResolver

        # El orden importa: primero se registra lo que ocurrió, luego se decide
        # sobre ello. Al revés, el resolutor decidiría sobre una tabla vacía y
        # devolvería `insufficient_evidence` para siempre.
        registro = NeuronEducationApplicationRecorder(self.db_path).record_once()

        # Primero se resuelve lo pendiente, luego se prepara más. Al revés, el
        # ciclo acumulaba lecciones en `lesson_prepared` para siempre: 7 sesiones
        # con `post_score` a NULL y `result='uncertain'`, y la hipótesis de cada
        # una en `pending` sin que nadie la cerrara.
        #
        # El resolutor es conservador por diseño: sin runs medidos suficientes
        # devuelve `insufficient_evidence` y deja la sesión viva. Eso no es un
        # fallo, es negarse a promover por autorreporte.
        resolucion = NeuronEducationResolver(self.db_path).resolve_once()

        result = NeuronEducationCycle(self.db_path).run_once()
        result["run_ref"] = run_ref
        result["education_applications"] = registro
        result["education_resolution"] = resolucion
        result["stable_memory_written"] = False
        # Promover a estable es HUMAN_REQUIRED. El resolutor sólo mueve
        # versiones experimentales, que son reversibles y quedan marcadas.
        result["stable_neuron_promotion"] = False
        # Este ciclo escribe sesiones y puede resolver/revertir una versión. El
        # contrato general del worker rechaza correctamente cualquier efecto
        # sin recibo; antes el handler mutaba la DB y después la tarea quedaba
        # en retry_wait como si hubiese fallado. Verificamos los identificadores
        # que los propios stores acaban de devolver y dejamos provenance DB.
        session_refs = {
            str(value)
            for value in (
                result.get("session_id"),
                resolucion.get("session_id"),
            )
            if value
        }
        if session_refs:
            with sqlite3.connect(self.db_path) as conn:
                verified_refs = [
                    session_id
                    for session_id in session_refs
                    if conn.execute(
                        "SELECT 1 FROM neuron_education_sessions WHERE session_id=?",
                        (session_id,),
                    ).fetchone()
                ]
            receipt = EffectReceipt(
                action="update_neuron_learning",
                target=f"neuron_education:{task.id}",
                execution={
                    "session_ids": sorted(session_refs),
                    "resolution": resolucion.get("decision"),
                },
                postcondition={
                    "passed": len(verified_refs) == len(session_refs),
                    "sessions_verified": len(verified_refs),
                },
                verified=len(verified_refs) == len(session_refs),
                verifier="neuron_education_database_postcondition",
                evidence_refs=[
                    f"sqlite:neuron_education_sessions:{session_id}"
                    for session_id in verified_refs
                ],
                rollback_ref=resolved_rollback
                if (resolved_rollback := resolucion.get("rollback_ref"))
                else None,
            )
            result["effect_receipt"] = receipt.model_dump(mode="json")
            result["status"] = "completed"
        return result

    def _self_improvement_evaluation(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Ejecuta el ciclo de automejora sobre propuestas YA APROBADAS por un humano.

        Este handler **no crea ni aprueba propuestas**. `create_candidate`
        (`self_improvement/bridge.py:102`) exige que la propuesta esté en estado
        `approved`, y `approve()` (`:67`) exige un `approved_by` no vacío. Es decir:
        un humano decide **qué dirección** se intenta; la máquina hace la
        **verificación rigurosa** (sandbox → medición → regression gate → canary),
        que es donde una firma humana no aportaría nada verificable.

        La medición no la declara el propio candidato: `VitalityEvaluationProvider`
        lee las cinco puntuaciones que el `Verifier` ya escribió en
        `verification_reports` durante runs reales, contra la suite inmutable
        `triade-vitality`. Si no hay evidencia suficiente, **falla en vez de
        adivinar**.

        Procesa **una** propuesta por ciclo, deliberadamente.
        """
        import sqlite3 as _sqlite3

        from triade.evaluation.provider_registry import (
            DEFAULT_EVALUATION_PROVIDER,
            build_evaluation_provider,
        )
        from triade.self_improvement.orchestrator import SelfImprovementOrchestrator

        payload = task.payload if isinstance(task.payload, dict) else {}

        with _sqlite3.connect(self.db_path) as conn:
            conn.row_factory = _sqlite3.Row
            # En una base nueva la tabla puede no existir todavía; un worker no
            # debe caerse por eso.
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='improvement_proposals'"
            ).fetchone():
                return {
                    "status": "no_target",
                    "reason": "no hay registro de propuestas de mejora todavía",
                    "run_ref": run_ref,
                }
            row = conn.execute(
                """SELECT proposal_id, payload_json FROM improvement_proposals
                   WHERE status = 'approved' ORDER BY rowid ASC LIMIT 1"""
            ).fetchone()
            pending = (
                None
                if row is not None
                else conn.execute(
                    """SELECT proposal_id, payload_json FROM improvement_proposals
                       WHERE status = 'open' ORDER BY rowid ASC LIMIT 1"""
                ).fetchone()
            )

        approver = "human"
        if row is None and pending is not None and _auto_approval_enabled():
            # El listón lo pone `auto_approval`, y lo consulta también el
            # planificador: si cada uno decidiera por su cuenta, el planificador
            # encolaría trabajo que el worker luego rechaza, o al revés.
            #
            # Antes aquí se aprobaba la primera propuesta abierta que hubiera,
            # sin mirar la calidad de la señal que la origina. El responsable
            # autorizó el 2026-08-11 la aprobación autónoma sólo por encima de
            # 0.9 de confianza.
            from triade.self_improvement.auto_approval import decide_for_proposal

            with _sqlite3.connect(self.db_path) as conn:
                conn.row_factory = _sqlite3.Row
                decision = decide_for_proposal(conn, str(pending["proposal_id"]))
            if not decision.allowed:
                # Un rechazo gobernado no es un fallo: deja rastro y se va.
                return {
                    "status": "observed",
                    "reason": f"propuesta no auto-aprobable: {decision.reason}",
                    "proposal_id": str(pending["proposal_id"]),
                    "auto_approval": decision.to_dict(),
                    "run_ref": run_ref,
                }
            # Aprobación por política, no humana. Decisión explícita del
            # responsable (2026-07-31): prefiere umbral altísimo a una firma que
            # no puede verificar. La búsqueda no queda sin límites: las
            # propuestas nacen de brechas MEDIDAS (ImprovementSignal con
            # observed/target/impact/confidence) y hay cooldown por señal
            # (self_improvement/store.py:144). El rigor se sostiene en el gate de
            # salida —tolerancia cero en trazabilidad y safety, suite inmutable—
            # no en una firma previa.
            # Se registra con el prefijo `auto:` para que NUNCA parezca que un
            # humano aprobó algo que no aprobó. Si hay una autorización
            # permanente declarada, el nombre del responsable se estampa DETRÁS
            # del prefijo, no en su lugar: la autorización es real, la decisión
            # concreta fue de la política, y auditar esto dentro de un año exige
            # poder distinguirlas.
            from triade.self_improvement.auto_approval import policy_approver

            aprobador = policy_approver()
            from triade.self_improvement.bridge import ImprovementNeuronFactoryBridge

            proposal_id = str(pending["proposal_id"])
            try:
                ImprovementNeuronFactoryBridge(self.db_path).approve(
                    proposal_id, approved_by=aprobador
                )
            except (ValueError, KeyError) as exc:
                return {
                    "status": "observed",
                    "reason": f"auto-aprobación rechazada: {exc}",
                    "proposal_id": proposal_id,
                    "run_ref": run_ref,
                }
            approver = aprobador
            row = pending

        if row is None:
            return {
                "status": "no_target",
                "reason": (
                    "no hay propuestas aprobadas"
                    if _auto_approval_enabled()
                    else "no hay propuestas aprobadas por un humano"
                ),
                "run_ref": run_ref,
            }

        proposal_id = str(row["proposal_id"])

        def _stamp(payload_out: dict[str, Any]) -> dict[str, Any]:
            """Todo camino de salida declara quién aprobó. Sin excepciones.

            Si el aprobador solo apareciera en el camino feliz, un fallo temprano
            borraría la única señal de que la propuesta se aprobó sin humano.
            """
            payload_out["proposal_id"] = proposal_id
            payload_out["run_ref"] = run_ref
            payload_out["approved_by"] = approver
            payload_out["human_approved_proposal"] = approver == "human"
            return payload_out

        neuron_id = str(payload.get("neuron_id") or "")
        version = str(payload.get("version") or "")
        if not neuron_id or not version:
            # Se nombra la capacidad que quedó sin destino. «No declara
            # neuron_id/version» leído en un panel parece una propuesta
            # malformada; el estado real es que nadie ha dicho a qué neurona
            # apunta esta mejora, y hasta el 2026-08-27 el contrato ni siquiera
            # permitía decirlo.
            capacidad = str(payload.get("requested_capability") or "sin capacidad")
            return _stamp(
                {
                    "status": "blocked",
                    "reason": (
                        f"la mejora de '{capacidad}' no tiene neurona destino"
                        " declarada (neuron_id/version)"
                    ),
                    "requested_capability": capacidad,
                }
            )

        # Idempotencia: si ya existe una candidata viva para esta terna, no se
        # crea una segunda. Dos candidatas para la misma (propuesta, neurona,
        # versión) serían dos verdades incompatibles sobre el mismo cambio.
        existing = self._existing_candidate(proposal_id, neuron_id, version)
        if existing is not None:
            return _stamp(
                {
                    "status": "observed",
                    "reason": "ya existe una candidata equivalente en curso",
                    "idempotent": True,
                    "candidate_id": existing,
                    "neuron_id": neuron_id,
                    "version": version,
                }
            )

        # El provider sale de un registro cerrado. Permitir un nombre arbitrario
        # dejaría que la propuesta eligiera su propio examinador.
        try:
            provider = build_evaluation_provider(
                str(payload.get("evaluation_provider") or DEFAULT_EVALUATION_PROVIDER),
                self.db_path,
            )
        except ValueError as exc:
            return _stamp({"status": "blocked", "reason": str(exc)})

        artifact_cutoff = str(payload.get("evaluated_since") or "")

        def _provider(candidate_id: str, artifact: dict[str, Any]):
            reference = dict(artifact)
            if artifact_cutoff:
                reference["created_at"] = artifact_cutoff
            return provider(candidate_id, reference)

        self._record_improvement_event(
            "self_improvement_started",
            run_ref,
            {"proposal_id": proposal_id, "neuron_id": neuron_id, "version": version},
        )
        try:
            result = SelfImprovementOrchestrator(self.db_path).run_once(
                proposal_id,
                neuron_id=neuron_id,
                version=version,
                configuration=dict(payload.get("configuration") or {"mode": "safe"}),
                evaluation_provider=_provider,
                canary_traffic_percent=int(payload.get("canary_traffic_percent") or 10),
                canary_tolerance=float(payload.get("canary_tolerance") or 0.02),
                canary_min_observations=int(
                    payload.get("canary_min_observations") or 3
                ),
                canary_max_observations=int(
                    payload.get("canary_max_observations") or 10
                ),
            )
        except (ValueError, KeyError) as exc:
            message = str(exc)
            # "Todavía no hay evidencia" no es lo mismo que "esto no sirve". Si
            # se tratara igual, una candidata perfectamente válida quedaría
            # descartada por haber llegado antes que sus datos. Se difiere para
            # reintentar cuando el sistema haya operado más.
            if "evidencia insuficiente" in message:
                self._record_improvement_event(
                    "self_improvement_deferred",
                    run_ref,
                    {"proposal_id": proposal_id, "reason": message},
                )
                return _stamp(
                    {
                        "status": "deferred",
                        "reason": message,
                        "defer_cause": "insufficient_candidate_observations",
                        "retryable": True,
                    }
                )
            self._record_improvement_event(
                "self_improvement_failed",
                run_ref,
                {"proposal_id": proposal_id, "reason": message},
            )
            return _stamp(
                {"status": "observed", "reason": f"ciclo no promovible: {message}"}
            )

        _stamp(result)
        result["stable_memory_written"] = False

        # Aprender del fallo. Antes de esto, `quarantined` era terminal: el gate
        # sabía qué métrica cayó y cuánto, y nadie leía ese detalle. Ahora cada
        # reprobación se archiva como lección por (capacidad, métrica) —
        # compartida entre neuronas— y se emite una señal dirigida a la métrica
        # que realmente falló. No relaja el gate: solo alimenta el intento
        # siguiente. Nunca puede tumbar el ciclo.
        if result.get("orchestrator_status") in {"quarantined", "rejected"}:
            try:
                from triade.self_improvement.failure_learning import FailureLearningLoop

                result["failure_learning"] = FailureLearningLoop(self.db_path).harvest()
            except (sqlite3.Error, ValueError, KeyError, OSError) as exc:
                result["failure_learning"] = {"error": f"{type(exc).__name__}: {exc}"}

        # Eventos explícitos por estado terminal del orquestador. El mejor
        # estado que esta tarea puede alcanzar es `canary_running`: nunca
        # promueve a estable por su cuenta.
        orchestrator_status = str(result.get("status") or "")
        self._record_improvement_event(
            {
                "canary_running": "candidate_canary_started",
                "quarantined": "candidate_quarantined",
            }.get(orchestrator_status, "candidate_evaluated"),
            run_ref,
            {
                "proposal_id": proposal_id,
                "candidate_id": result.get("candidate_id"),
                "orchestrator_status": orchestrator_status,
            },
        )
        result["stable_promotion_performed"] = False
        # El estado que devuelve el orquestador (promoted/quarantined/
        # canary_running) no es un estado de tarea: se reporta como observación
        # para que el ejecutor no lo interprete como éxito de promoción.
        result["orchestrator_status"] = result.get("status")
        result["status"] = "observed"
        return result

    def _existing_candidate(
        self, proposal_id: str, neuron_id: str, version: str
    ) -> str | None:
        """`candidate_id` de una candidata viva para esta terna, si la hay."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='improvement_candidate_links'"
            ).fetchone():
                return None
            row = conn.execute(
                """SELECT candidate_id FROM improvement_candidate_links
                WHERE proposal_id = ? AND neuron_id = ? AND version = ?
                  AND status NOT IN ('rejected','cancelled')
                ORDER BY rowid DESC LIMIT 1""",
                (proposal_id, neuron_id, version),
            ).fetchone()
        return str(row["candidate_id"]) if row else None

    def _record_improvement_event(
        self, event: str, run_ref: str, payload: dict[str, Any]
    ) -> None:
        """Deja rastro de cada etapa. Nunca puede tumbar el ciclo."""
        try:
            self.store.record_event(
                event,
                f"Automejora: {event}",
                run_ref=run_ref,
                status="observed",
                payload=payload,
            )
        except WORKER_OPERATION_ERRORS:
            # Perder una traza es malo; perder el ciclo por no poder trazarlo,
            # peor. El resultado canónico ya queda en los artefactos.
            pass

    def _self_improvement_canary_observation(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Acumula observaciones reales sobre el canary abierto.

        Separada de la evaluación a propósito: esperar dentro de `run_once()` a
        que ocurran suficientes conversaciones significaría sostener un lease
        durante horas. Aquí cada ciclo aporta lo que haya y se va.

        No promueve a estable. Un canary graduado dice "sobrevivió la ventana sin
        degradar", no "consolidado".
        """
        from triade.self_improvement.canary_observation import (
            CanaryObservationCollector,
        )

        payload = task.payload if isinstance(task.payload, dict) else {}
        collector = CanaryObservationCollector(self.db_path)
        result = collector.observe_once(
            candidate_id=str(payload.get("candidate_id") or "") or None,
            max_reports=int(payload.get("max_reports") or 5),
        )
        status = str(result.get("status") or "")

        if status == "no_canary":
            return {**result, "status": "no_target", "run_ref": run_ref}
        if status == "insufficient_candidate_observations":
            # No es un fallo: es que todavía no hay con qué decidir.
            return {
                **result,
                "status": "deferred",
                "defer_cause": "insufficient_candidate_observations",
                "retryable": True,
                "run_ref": run_ref,
            }

        self._record_improvement_event(
            {
                "rolled_back": "candidate_rolled_back",
                "graduated": "candidate_canary_graduated",
            }.get(status, "candidate_canary_observed"),
            run_ref,
            {
                "canary_id": result.get("canary_id"),
                "candidate_id": result.get("candidate_id"),
                "canary_status": status,
                "observation_count": result.get("observation_count"),
            },
        )
        return {
            **result,
            "canary_status": status,
            "status": "observed",
            "run_ref": run_ref,
        }

    def _write_governed_text_artifact(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.runtime.governed_capability import GovernedFileWriteCapability

        target = str(task.payload.get("target") or "")
        content = str(task.payload.get("content") or "")
        authorized_root = str(task.payload.get("authorized_root") or "")
        if not target or not authorized_root:
            return {
                "status": "blocked",
                "reason": "target_and_authorized_root_required",
            }
        capability = GovernedFileWriteCapability(
            target, content, task_dir / "rollback", authorized_root=authorized_root
        )
        prepared = capability.prepare()
        execution = capability.execute()
        receipt = capability.verify()
        if not receipt.verified:
            capability.rollback()
            rollback = capability.verify_rollback()
            return {
                "status": "error",
                "error": "file_postcondition_failed",
                "rollback": rollback.model_dump(mode="json"),
            }
        return {
            "status": "completed",
            "task_type": task.task_type,
            "prepared": prepared,
            "execution": execution,
            "effect_receipt": receipt.model_dump(mode="json"),
            "rollback_spec": capability.rollback_spec(),
            "run_ref": run_ref,
        }

    def _safety_for_task(self, task: WorkerTask, run_ref: str):
        signals = SignalPacket(
            run_id=run_ref,
            intent="worker",
            tone="operational",
            urgency="low",
            risk="low",
            pv7={},
            notes=[task.task_type],
        )
        plan = PlanPacket(
            run_id=run_ref,
            goal=f"Ejecutar worker task {task.task_type}",
            steps=["safe_background_cycle"],
            tools=[],
        )
        memory = MemoryPacket(run_id=run_ref, semantic_recall={"enabled": False})
        # Regulación real de Cristal (pura, sin I/O) en vez de un CrystalPacket
        # estático "stable" fijo — los ciclos de fondo deben pasar por el
        # mismo regulador que los runs conversacionales, no por un stub.
        crystal = Crystal().regulate(signals, memory)
        return Safety().review(signals, plan, crystal=crystal, memory=memory)

    def _publish_qualia_experience(
        self,
        run_ref: str,
        task_type: str,
        neuron_type: str,
        observation: str,
        extracted_pattern: str = "",
        proposed_learning: str = "",
        confidence: float = 0.6,
        risk: str = "low",
        usefulness: float = 0.5,
        ingest_learning: bool | None = None,
    ) -> dict[str, Any] | None:
        try:
            bus = QualiaBus(db_path=self.db_path)
            exp = NeuronExperience(
                run_id=run_ref,
                neuron_id=f"worker:{task_type}",
                neuron_type=neuron_type,
                mission=f"Living Worker ejecutó {task_type}",
                source="living_worker",
                source_type="worker_task",
                observation=observation[:1000],
                extracted_pattern=extracted_pattern[:1000],
                proposed_learning=proposed_learning[:1000],
                confidence=confidence,
                risk=risk,
                usefulness=usefulness,
                evidence_refs=[f"worker:{run_ref}", f"task:{task_type}"],
            )
            # Telemetría Qualia no se convierte en aprendizaje por defecto.
            result = bus.publish_experience(
                exp,
                ingest_learning=False if ingest_learning is None else ingest_learning,
            )
            return {
                "published": True,
                "experience_id": exp.id,
                "state": result.get("state", {}).to_dict()
                if hasattr(result.get("state"), "to_dict")
                else result.get("state"),
            }
        except WORKER_OPERATION_ERRORS as exc:
            record_internal_error(
                "worker_loop.qualia_publish",
                exc,
                run_id=run_ref,
                payload={
                    "module": __name__,
                    "function": "_publish_qualia_experience",
                    "operation": "publish_worker_qualia_experience",
                    "task_type": task_type,
                },
                db_path=self.db_path,
            )
            return {"published": False, "error": str(exc)}

    def _pulse_check(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from apps.services import build_system_pulse

        pulse = build_system_pulse(sync_relay=False)
        return {
            "status": "completed",
            "pulse": pulse,
            "policy": "local_only_no_external_relay_sync",
            "qualia": {
                "published": False,
                "reason": "heartbeat_is_telemetry_not_experience",
            },
        }

    def _pending_learning_review(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        # Consume regresiones reales que ya dejó el RegressionGate. La cosecha
        # es idempotente por (report_id, metric_id); sin este consumidor, los
        # informes anteriores al arranque quedaban fuera del circuito y sólo
        # una regresión futura podía abrir la automejora.
        from triade.self_improvement.failure_learning import FailureLearningLoop

        failure_learning = FailureLearningLoop(self.db_path).harvest(limit=5)
        pipe = LearningPipeline(db_path=self.db_path)
        sandbox = WorkerSandbox(task_dir)
        processed = []
        for candidate in pipe.list_candidates(status="candidate", limit=5):
            sb = sandbox.run(
                "validate_learning_candidate", candidate, timeout=config.task_timeout
            )
            if sb.get("identity_red_flag"):
                processed.append(
                    pipe.reject(
                        candidate["candidate_id"],
                        reason="worker sandbox detected identity_core risk",
                    )
                )
            else:
                processed.append(pipe.evaluate(candidate["candidate_id"]))
        for candidate in pipe.list_candidates(status="evaluated", limit=5):
            verified = pipe.verify(candidate["candidate_id"])
            processed.append(verified)
        qualia = (
            self._publish_qualia_experience(
                run_ref,
                "pending_learning_review",
                "worker_learning",
                f"Worker realizó {len(processed)} transiciones de aprendizaje.",
                proposed_learning="Transiciones candidate→evaluated→internally_checked registradas.",
                ingest_learning=False,
            )
            if processed
            else {"published": False, "reason": "no_state_transition"}
        )
        return {
            "status": "completed",
            "processed_count": len(processed),
            "processed": processed,
            "failure_learning": failure_learning,
            "stable_memory_written": False,
            "qualia": qualia,
        }

    # ── Aprendizaje productivo ───────────────────────────────────────────
    # Las tres etapas que antes sólo existían en `scripts/run_knowledge_zero_to_one.py`.
    # El script demostraba el circuito; estos handlers lo hacen ocurrir solo.

    def _learning_candidate_generation(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Extrae una proposición aprendible de un run ya terminado.

        Se ejecuta después de responder al usuario: aprender nunca puede
        retrasar una conversación.
        """
        from triade.learning.candidate_producer import (
            ExperienceLearningCandidateProducer,
        )

        payload = task.payload if isinstance(task.payload, dict) else {}
        source_run_id = str(payload.get("source_run_id") or "")
        mensaje = str(payload.get("message") or "")
        role = str(payload.get("role") or "user")
        if not source_run_id or not mensaje:
            return {
                "status": "completed",
                "effect": "no_op",
                "skipped_reason": "payload_incompleto",
                "stable_memory_written": False,
            }

        producer = ExperienceLearningCandidateProducer(self.db_path)
        resultado = producer.produce(
            run_id=source_run_id,
            message=mensaje,
            role=role,
            domain=str(payload.get("domain") or "conversation"),
        )
        if not resultado.candidates:
            return {
                "status": "completed",
                "effect": "no_op",
                "skipped_reason": resultado.rejected[0]["reason"]
                if resultado.rejected
                else "sin_aprendizaje",
                "stable_memory_written": False,
            }

        candidato = resultado.candidates[0]
        creado = producer.persist(candidato)
        candidate_ref = task_dir / "candidate.json"
        candidate_ref.write_text(
            json.dumps(candidato.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        # El recibo tiene que apuntar a la fila que de verdad guarda el saber,
        # y esa no siempre lleva el `candidate_id` que acaba de generarse.
        # `candidate_id` es un `uuid4` nuevo en cada intento, mientras que
        # `persist()` deduplica por `normalized_summary`: ante un duplicado
        # devuelve False y **no** escribe fila, así que buscar el id nuevo no
        # encuentra nada. El recibo salía `verified=False` sobre un
        # `status="completed"` y `ExecutionResult` lo rechazaba con
        # `completed_requires_verified_effect_receipt`; tres reintentos
        # deterministas después, la tarea moría en `dead_letter`. Medido el
        # 2026-08-27 sobre la base viva: los 4 `dead_letter` del día eran los 4
        # duplicados del día. El saber ya estaba en la cola; lo que fallaba era
        # el sitio donde se comprobaba.
        with sqlite3.connect(self.db_path) as conn:
            fila = conn.execute(
                "SELECT candidate_id FROM learning_queue WHERE candidate_id=?",
                (candidato.candidate_id,),
            ).fetchone()
            if fila is None:
                fila = conn.execute(
                    "SELECT candidate_id FROM learning_queue"
                    " WHERE normalized_summary=?",
                    (candidato.normalized_content,),
                ).fetchone()
        stored_id = str(fila[0]) if fila else None
        candidate_verified = candidate_ref.is_file() and stored_id is not None
        receipt = EffectReceipt(
            action="persist_learning_candidate" if creado else "observe",
            target=stored_id or candidato.candidate_id,
            execution={
                "source_run_id": source_run_id,
                "created": creado,
                "produced_candidate_id": candidato.candidate_id,
            },
            postcondition={"passed": candidate_verified, "stored_id": stored_id},
            verified=candidate_verified,
            verifier="learning_candidate_artifact_postcondition",
            evidence_refs=[
                str(candidate_ref),
                f"sqlite:learning_queue:{stored_id or candidato.candidate_id}",
            ],
        )
        return {
            "status": "completed",
            "effect": "candidate_created" if creado else "duplicate_skipped",
            # El id que se reporta es el de la fila viva. Devolver el uuid
            # descartado dejaba una referencia que no resuelve contra la tabla.
            "candidate_id": stored_id or candidato.candidate_id,
            "candidate_type": candidato.type,
            "created": creado,
            "stable_memory_written": False,
            "effect_receipt": receipt.model_dump(mode="json"),
        }

    def _learning_candidate_deduplication(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Agrupa duplicados sin borrar filas. Idempotente y reversible."""
        from triade.learning.deduplication import LearningDeduplicator

        dedup = LearningDeduplicator(self.db_path)
        reporte = dedup.analyze()
        escritos = dedup.apply(reporte)
        (task_dir / "dedup.json").write_text(
            json.dumps(reporte.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "status": "completed",
            # Una tarea que corre y no agrupa nada no es un éxito: es un no-op,
            # y decirlo evita que el panel parezca vivo sin estarlo.
            "effect": "grouped" if escritos else "no_op",
            "processed_count": reporte.total_rows,
            "grouped_count": escritos,
            "unique_contents": reporte.unique_contents,
            "rows_deleted": 0,
            "stable_memory_written": False,
        }

    def _learning_claim_distillation(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Da un hijo sondeable a los candidatos `web` que no lo son.

        No toca al padre: escribe una fila `distilled` que apunta a él. Ver
        `AssertionPromoter` para por qué no se reescribe la transcripción.
        """
        from triade.learning.assertion_promoter import AssertionPromoter

        reporte = AssertionPromoter(self.db_path).run()
        (task_dir / "distillation.json").write_text(
            json.dumps(reporte.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "status": "completed",
            # Inspeccionar 40 padres y no destilar ninguno es un no-op, no un
            # éxito: casi ninguna fuente afirma un hecho con sujeto nombrable, y
            # el panel no debe parecer vivo por haber corrido.
            "effect": "distilled" if reporte.written else "no_op",
            "processed_count": reporte.inspected,
            "distilled_count": reporte.distilled,
            "written_count": reporte.written,
            "rows_deleted": 0,
            "stable_memory_written": False,
        }

    def _neural_learning_distribution(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Asigna conocimiento consolidado a una neurona, sin saltar evidencia."""
        from triade.neurons.learning_router import NeuralLearningRouter

        payload = task.payload if isinstance(task.payload, dict) else {}
        candidate_id = str(payload.get("candidate_id") or "")
        if not candidate_id:
            return {
                "status": "completed",
                "effect": "no_op",
                "skipped_reason": "sin_candidate_id",
                "stable_memory_written": False,
            }
        router = NeuralLearningRouter(self.db_path)
        try:
            routed = router.route(candidate_id)
        except (KeyError, ValueError) as exc:
            rejected = router.record_rejection(candidate_id, str(exc))
            receipt = EffectReceipt(
                action="reject_neural_learning",
                target=candidate_id,
                execution={"reason": str(exc)},
                postcondition={"passed": True, "event_id": rejected["event_id"]},
                verified=True,
                verifier="neuron_education_event_postcondition",
                evidence_refs=[
                    f"sqlite:neuron_education_events:{rejected['event_id']}"
                ],
            )
            return {
                "status": "completed",
                "effect": "rejected",
                "candidate_id": candidate_id,
                "skipped_reason": str(exc),
                "stable_memory_written": False,
                "rejection": rejected,
                "effect_receipt": receipt.model_dump(mode="json"),
            }
        (task_dir / "neural-learning-route.json").write_text(
            json.dumps(routed, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        route_event_id = routed.get("event_id")
        evidence_refs = [
            f"sqlite:neuron_learning_assignments:{routed['assignment_id']}"
        ]
        if route_event_id is not None:
            evidence_refs.append(f"sqlite:neuron_education_events:{route_event_id}")
        receipt = EffectReceipt(
            action=(
                "route_neural_learning" if routed["status"] == "routed" else "observe"
            ),
            target=str(routed["assignment_id"]),
            execution={"candidate_id": candidate_id},
            postcondition={"passed": True, "event_id": route_event_id},
            verified=True,
            verifier="neuron_learning_assignment_postcondition",
            evidence_refs=evidence_refs,
            rollback_ref=f"neuron_learning_assignment:{routed['assignment_id']}",
        )
        return {
            **routed,
            "status": "completed",
            "route_status": routed["status"],
            "effect": routed["status"],
            "stable_memory_written": False,
            "effect_receipt": receipt.model_dump(mode="json"),
        }

    def _learning_evidence_generation(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Mide un candidato con control/tratamiento y lo verifica si mejora.

        La revisión va en el mismo handler porque comparte el lease del
        candidato: separarla abriría una ventana en la que otro obrero podría
        promover con evidencia a medio escribir.
        """
        from triade.learning.evidence_producer import LearningEvidenceProducer
        from triade.learning.knowledge_probe import build_probe

        payload = task.payload if isinstance(task.payload, dict) else {}
        candidate_id = str(payload.get("candidate_id") or "")
        if not candidate_id:
            return {
                "status": "completed",
                "effect": "no_op",
                "skipped_reason": "sin_candidate_id",
                "stable_memory_written": False,
            }

        sonda = build_probe(self.db_path, candidate_id)
        if sonda is None:
            # El veredicto se registra antes de salir. Mientras no se registró,
            # el `NOT EXISTS` del planner seguía siendo cierto y volvía a elegir
            # el mismo candidato: 465 intentos idénticos (F-037). El planner ya
            # no debería mandar aquí a un candidato inmedible —usa la misma
            # sonda para elegir—, pero una tarea encolada a mano sí puede.
            from triade.learning.evidence_bridge import LearningEvidenceBridge

            try:
                LearningEvidenceBridge(db_path=self.db_path).record_inconclusive(
                    candidate_id,
                    decision="not_measurable",
                    reason="sin dato distintivo que preguntar",
                )
            except (ValueError, sqlite3.Error):
                pass
            return {
                "status": "completed",
                "effect": "no_op",
                "skipped_reason": "sin_prueba_objetiva",
                "candidate_id": candidate_id,
                "stable_memory_written": False,
            }

        client = self._observable_ollama_client(
            task,
            run_ref,
            cognitive_function="learning_evaluation",
            artifact="learning_evidence",
            consumer="LearningEvidenceProducer",
        )
        if not client.health().get("ok"):
            # Esperar recursos no puede gastar un intento del candidato.
            return {
                "status": "deferred",
                "effect": "deferred",
                "skipped_reason": "ollama_no_disponible",
                "candidate_id": candidate_id,
                "stable_memory_written": False,
            }

        def generate(prompt: str) -> str:
            r = client.generate(
                config.model if hasattr(config, "model") else "qwen2.5:3b-instruct",
                prompt,
                options={"temperature": 0, "seed": 7731},
            )
            return str(getattr(r, "text", "") or "")

        producer = LearningEvidenceProducer(
            self.db_path, generate=generate, temperature=0.0, seed=7731
        )
        outcome = producer.produce(
            candidate_id=candidate_id,
            question=sonda.question,
            evaluator=sonda.evaluator,
            repetitions=int(payload.get("repetitions") or 5),
        )
        (task_dir / "evidence.json").write_text(
            json.dumps(outcome.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        promocion = {"promoted": False, "reason": f"decision={outcome.decision}"}
        if outcome.decision == "improved":
            promocion = producer.promote_if_verified(candidate_id)

        failure_learning: dict[str, Any] | None = None
        if outcome.decision == "regressed" and outcome.regression_report_id:
            # Este es el primer productor natural de señales de automejora.
            # Antes, FailureLearningLoop sólo se cosechaba DESPUÉS de una
            # self_improvement_evaluation reprobada. Pero esa evaluación exige
            # una propuesta nacida de una señal: el circuito era circular y los
            # regression_reports reales quedaban sin consumidor para siempre.
            from triade.self_improvement.failure_learning import FailureLearningLoop

            failure_learning = FailureLearningLoop(self.db_path).harvest(limit=1)

        return {
            "status": "completed",
            "effect": f"evidence_{outcome.decision}",
            "candidate_id": candidate_id,
            "decision": outcome.decision,
            "control_mean": outcome.control_mean,
            "treatment_mean": outcome.treatment_mean,
            "absolute_delta": outcome.absolute_delta,
            "regression_report_id": outcome.regression_report_id,
            "promoted": promocion.get("promoted", False),
            "promotion_reason": promocion.get("reason"),
            "failure_learning": failure_learning,
            # `evidence_verified` no es `stable`: eso exige firma humana G3.
            "stable_memory_written": False,
        }

    def _semantic_memory_governance(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        governance = SemanticMemoryGovernance(db_path=self.db_path).doctor()
        # La tarea se llamaba «gobernanza» y sólo diagnosticaba: llamaba a
        # `doctor()`, publicaba el resultado y no tocaba nada. Mientras tanto los
        # 351 documentos de la base llevaban vector de `triade-local-hash:64`, el
        # respaldo que `SemanticContinuity` guarda porque su único llamador
        # productivo pasa `auto_ollama_embed=False` —y hace bien: embeber en la
        # ruta de una conversación la frena—. El resultado era que la similitud
        # vectorial no encontraba nada nunca: `matches_count: 0` y
        # `skipped_model: 350` en cada `semantic_recall`, con el canal de
        # palabras clave tapando el agujero.
        #
        # El motor que sabe embeber de verdad ya existía y no lo disparaba nadie.
        # Aquí es donde toca: fuera de la conversación, acotado, e incremental.
        reembedding = SemanticEmbeddingEngine(
            store=SemanticMemoryStore(db_path=self.db_path),
            client=self._observable_ollama_client(
                task,
                run_ref,
                cognitive_function="semantic_embedding",
                artifact="semantic_embeddings",
                consumer="SemanticMemoryStore",
            ),
        ).reembed_stale(limit=int(task.payload.get("reembed_limit") or 10))
        qualia = self._publish_qualia_experience(
            run_ref,
            "semantic_memory_governance",
            "worker_governance",
            f"Gobernanza semántica ejecutada: {governance.get('status', 'unknown')}; "
            f"{reembedding.get('reembedded_ok', 0)} documentos reembebidos de "
            f"{reembedding.get('stale_found', 0)} obsoletos.",
            extracted_pattern=str(governance),
        )
        return {
            "status": "completed",
            "governance": governance,
            "reembedding": reembedding,
            "qualia": qualia,
        }

    def _neuron_candidate_formation(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        pulse = {
            "status": "unknown",
            "summary": "worker background scan",
            "federation": {"android_native_online": 0, "android_llm_hosts": 0},
        }
        raw = candidates_from_system_debt(pulse_summary=pulse)
        formed = form_candidates(raw)
        qualia = self._publish_qualia_experience(
            run_ref,
            "neuron_candidate_formation",
            "worker_formation",
            f"Formación de candidatos: {len(raw)} raw → {len(formed)} formados.",
            extracted_pattern=str([c.get("name", "") for c in formed[:5]]),
        )
        return {
            "status": "completed",
            "raw_count": len(raw),
            "formed_count": len(formed),
            "candidates": formed,
            "qualia": qualia,
        }

    def _experimental_neuron_activity(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.core.neuron_mission_selector import select_relevant_missions
        from triade.core.neuron_missions import NeuronMissionStore

        mission_id = task.payload.get("mission_id")
        if mission_id is not None:
            store = NeuronMissionStore(db_path=self.db_path)
            mission = store.get_mission(int(mission_id))
            selection = select_relevant_missions(
                user_input=str(
                    task.payload.get("query") or task.payload.get("user_input") or ""
                ),
                domain=str(
                    task.payload.get("domain")
                    or (mission.domain if mission else "")
                    or ""
                ),
                memory_context=task.payload.get("memory_context")
                or task.payload.get("context")
                or {},
                db_path=self.db_path,
                limit=5,
            )
            relevant_ids = {
                int(item["id"])
                for item in (selection.get("selected") or [])
                if item.get("id") is not None
            }
            if mission is None:
                blocked = {
                    "status": "blocked",
                    "decision": "mission_not_found",
                    "mission_id": int(mission_id),
                    "mission_selection": selection,
                    "mission_selection_policy": selection.get("policy", {}),
                    "relevant_missions": selection.get("selected", []),
                    "stable_memory_written": False,
                }
                qualia = self._publish_qualia_experience(
                    run_ref,
                    "experimental_neuron_activity",
                    "worker_neuron_mission_blocked",
                    f"Misión neuronal {mission_id} no encontrada; ejecución bloqueada.",
                    extracted_pattern=str(
                        {"mission_id": mission_id, "decision": "mission_not_found"}
                    ),
                    proposed_learning="No ejecutar misiones neuronales inexistentes.",
                    confidence=0.1,
                    usefulness=0.1,
                    ingest_learning=False,
                )
                return {**blocked, "qualia": qualia}
            if int(mission_id) not in relevant_ids:
                blocked = {
                    "status": "blocked",
                    "decision": "blocked_by_relevance",
                    "mission_id": int(mission_id),
                    "mission_title": mission.title,
                    "mission_domain": mission.domain,
                    "mission_selection": selection,
                    "mission_selection_policy": selection.get("policy", {}),
                    "relevant_missions": selection.get("selected", []),
                    "stable_memory_written": False,
                }
                qualia = self._publish_qualia_experience(
                    run_ref,
                    "experimental_neuron_activity",
                    "worker_neuron_mission_blocked",
                    f"Misión neuronal {mission_id} bloqueada por relevancia insuficiente.",
                    extracted_pattern=str(
                        {
                            "mission_id": mission_id,
                            "decision": "blocked_by_relevance",
                            "selected_count": selection.get("count", 0),
                        }
                    ),
                    proposed_learning="No ejecutar misiones neuronales irrelevantes.",
                    confidence=0.2,
                    usefulness=0.2,
                    ingest_learning=False,
                )
                return {**blocked, "qualia": qualia}
            mission_result = NeuronMissionExecutor(db_path=self.db_path).execute(
                mission_id=int(mission_id),
                run_ref=run_ref,
                task_payload=task.payload,
                task_dir=task_dir,
                config=config,
            )
            qualia = self._publish_qualia_experience(
                run_ref,
                "experimental_neuron_activity",
                "worker_neuron_mission",
                str(
                    mission_result.get("observation")
                    or mission_result.get("decision")
                    or "Misión neuronal ejecutada."
                ),
                extracted_pattern=str(
                    {
                        "mission_id": mission_result.get("mission_id"),
                        "cycle_id": mission_result.get("cycle_id"),
                        "evidence_id": mission_result.get("evidence_id"),
                        "score_id": mission_result.get("score_id"),
                        "decision": mission_result.get("decision"),
                    }
                ),
                proposed_learning=str(mission_result.get("proposed_learning") or "")[
                    :1000
                ],
                confidence=float(mission_result.get("composite_score") or 0.6),
                usefulness=float(mission_result.get("composite_score") or 0.5),
                ingest_learning=False,
            )
            return {
                **mission_result,
                "stable_memory_written": False,
                "qualia": qualia,
                "mission_selection": selection,
                "mission_selection_policy": selection.get("policy", {}),
                "relevant_missions": selection.get("selected", []),
            }

        signals = SignalPacket(
            run_id=run_ref,
            intent="worker",
            tone="operational",
            urgency="low",
            risk="low",
            notes=["background"],
        )
        query = str(
            task.payload.get("query") or "pulso memoria federacion modelo estado worker"
        )
        domain = str(task.payload.get("domain") or "")
        selection = select_relevant_missions(
            user_input=query,
            domain=domain or None,
            db_path=self.db_path,
            limit=5,
        )
        relevant = selection.get("selected") or []
        first_mission_id = relevant[0]["id"] if relevant else None
        if first_mission_id is not None:
            mission_result = NeuronMissionExecutor(db_path=self.db_path).execute(
                mission_id=int(first_mission_id),
                run_ref=run_ref,
                task_payload={
                    **task.payload,
                    "selected_by_relevance": True,
                    "selection_result": selection,
                },
                task_dir=task_dir,
                config=config,
            )
            qualia = self._publish_qualia_experience(
                run_ref,
                "experimental_neuron_activity",
                "worker_neuron_relevant_mission",
                str(
                    mission_result.get("observation")
                    or mission_result.get("decision")
                    or "Misión neuronal ejecutada por relevancia."
                ),
                extracted_pattern=str(
                    {
                        "mission_id": mission_result.get("mission_id"),
                        "cycle_id": mission_result.get("cycle_id"),
                        "evidence_id": mission_result.get("evidence_id"),
                        "score_id": mission_result.get("score_id"),
                        "decision": mission_result.get("decision"),
                        "relevance_count": selection.get("count"),
                    }
                ),
                proposed_learning=str(mission_result.get("proposed_learning") or "")[
                    :1000
                ],
                confidence=float(mission_result.get("composite_score") or 0.6),
                usefulness=float(mission_result.get("composite_score") or 0.5),
                ingest_learning=False,
            )
            return {
                **mission_result,
                "stable_memory_written": False,
                "qualia": qualia,
                "mission_selection": selection,
                "mission_selection_policy": selection.get("policy", {}),
                "relevant_missions": selection.get("selected", []),
            }

        activity = run_experimental_neurons(
            db_path=str(self.db_path),
            user_input="pulso memoria federacion modelo estado worker",
            context={"domain": "system_governance", "active_neuron": "living-workers"},
            signals=signals,
            edge_usage={
                "used_edge": False,
                "accepted": False,
                "keywords": ["pulso", "memoria", "federacion"],
            },
            system_events=[],
        )
        ids = NeuronActivityStore(db_path=self.db_path).record_run_activity(
            run_ref, activity
        )
        activity["db_activity_ids"] = ids
        qualia = self._publish_qualia_experience(
            run_ref,
            "experimental_neuron_activity",
            "worker_neuron_activity",
            f"Actividad experimental: {len(ids)} registros de actividad.",
            extracted_pattern=str(activity.get("summary", "")),
        )
        return {"status": "completed", "activity": activity, "qualia": qualia}

    def _neuron_autopromotion(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        # Ver el comentario en `core/runner.py`: tres subsistemas del mismo
        # proceso llaman a `promote()`. El lock decide de quién es el turno.
        coord = OrchestratorCoordinator(db_path=self.db_path)
        with coord.guard(
            coord.LOCK_NEURON_PROMOTION, "workers", ttl=180.0
        ) as es_mi_turno:
            if not es_mi_turno:
                return {
                    "status": "skipped",
                    "reason": "otro subsistema tiene el turno de promoción",
                }
            events = NeuronAutopromoter(db_path=self.db_path).promote()
        qualia = (
            self._publish_qualia_experience(
                run_ref,
                "neuron_autopromotion",
                "worker_autopromotion",
                f"Promoción gobernada produjo {len(events)} transiciones.",
                extracted_pattern=str(events[:3]),
                ingest_learning=False,
            )
            if events
            else {"published": False, "reason": "no_state_transition"}
        )
        return {
            "status": "completed",
            "events": events,
            "stable_promotion_requires_readiness": True,
            "qualia": qualia,
        }

    def _federation_inbox_review(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        federation = Federation(db_path=self.db_path)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT exchange_id, source_node_id, target_node_id, exchange_type, risk_level, safety_status, decision, reason, created_at FROM federated_exchange_log ORDER BY id DESC LIMIT 10"
            ).fetchall()
        return {
            "status": "completed",
            "doctor": federation.doctor(),
            "recent_exchanges": [dict(row) for row in rows],
            "external_network": False,
        }

    def _peft_canary_observation(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Genera con el adaptador en canary y registra la observación.

        Mide lo que este eslabón puede medir: que el adaptador **sirve** sin
        degradarse en fallo. Que además sea mejor que la base ya lo decidió
        `enroll()` con las métricas OOD y de olvido catastrófico del manifiesto;
        repetir aquí esa evaluación exigiría el conjunto de validación completo y
        no cabe en un ciclo de worker.

        La activación no se toca: sigue exigiendo firma humana nombrada.
        """
        from triade.training.peft_canary import PeftCanaryServer
        from triade.training.serving_governance import GovernedPeftServing

        payload = task.payload if isinstance(task.payload, dict) else {}
        version_id = str(payload.get("version_id") or "")
        adapter_path = str(payload.get("adapter_path") or "")
        if not version_id or not adapter_path:
            return {
                "status": "completed",
                "effect": "no_op",
                "skipped_reason": "sin_version_o_adaptador",
                "stable_memory_written": False,
            }
        if not Path(adapter_path).exists():
            return {
                "status": "completed",
                "effect": "no_op",
                "skipped_reason": "adaptador_ausente_en_disco",
                "version_id": version_id,
                "stable_memory_written": False,
            }

        adapters_root = Path(adapter_path).parent
        generacion = PeftCanaryServer(self.db_path, adapters_root).generate(
            adapter_path,
            "Responde exactamente: canary-ok",
            max_new_tokens=48,
        )
        completada = generacion.get("status") == "completed" and bool(
            generacion.get("response")
        )
        serving = GovernedPeftServing(self.db_path, adapters_root)
        observacion = serving.observe(
            version_id,
            # La escala la fija `baseline_quality` en la inscripción; 1.0 pasa y
            # -10.0 hunde el canary, igual que en la verificación de fase 13.
            quality=1.0 if completada else -10.0,
            latency_ms=float(generacion.get("latency_ms") or 0.0),
            success=completada,
            evidence_ref=f"worker:{run_ref}:peft-canary-generation",
        )
        (task_dir / "peft_canary_observation.json").write_text(
            json.dumps(
                {"generation": generacion, "observation": observacion},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "status": "completed",
            "effect": f"canary_{observacion.get('status')}",
            "version_id": version_id,
            "canary_status": observacion.get("status"),
            "latency_ms": generacion.get("latency_ms"),
            "activation_requires_human": True,
            "stable_memory_written": False,
        }

    def _stable_consolidation_review(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Revisa candidatos con evidencia suficiente y solo entonces permite consolidar.

        Listaba únicamente `validated_in_runs`, un estado con cero filas en toda
        la vida de la base: aunque la tarea llegase, el bucle no iteraba nunca.
        `evidence_verified` es la otra puerta a la misma medición y es la que el
        productor de evidencia usa hoy. Los umbrales no cambian: quien decide
        sigue siendo `pipe.consolidate()`.

        Y por tercera vez la misma enfermedad, un escalón más abajo: aquí había
        otra copia escrita a mano de la lista de estados, sin
        `internally_checked`. El planner ya contaba 16 candidatos usados que
        cumplían ambos umbrales, encolaba la tarea, y el handler iteraba sobre
        cero: `stable: 0` con la tarea en `completed`. Dueño del vocabulario hay
        uno —`LearningPipeline.CONSOLIDATABLE_STATES`— y quien mantiene su propia
        copia se queda atrás en cuanto el dueño la amplía.
        """
        pipe = LearningPipeline(db_path=self.db_path)
        sandbox = WorkerSandbox(task_dir)
        consolidated = []
        rejected = []
        # `list_candidates` ordena por `id DESC`: con 713 candidatos en estado
        # consolidable, los cinco primeros son los más recientes, y los recientes
        # son justo los que aún no se han usado. El planner contaba 16 que sí
        # cumplen los dos umbrales y el handler se llevaba cinco que no: vuelven
        # a discrepar, y la tanda entera se rechaza por usos insuficientes.
        #
        # Es la misma hambre que ya se corrigió en la selección de evidencia: un
        # escaneo por recencia mata de hambre a los que se usan. Se filtra por la
        # misma condición con la que el planner decidió que había trabajo —los
        # umbrales siguen siendo de `LearningPipeline`, y quien decide sigue
        # siendo `consolidate()`— y se procesan cinco de entre los que califican.
        elegibles = pipe.list_consolidatable(limit=5)
        for candidate in elegibles:
            sb = sandbox.run(
                "analyze_memory_candidate", candidate, timeout=config.task_timeout
            )
            if sb.get("status") != "ok" or not candidate.get("source_ref"):
                rejected.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "reason": "sandbox_check_failed",
                    }
                )
                continue
            try:
                result = pipe.consolidate(
                    candidate["candidate_id"],
                    approved_by=f"worker-stable-review:{run_ref}",
                )
                consolidated.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "document_id": result.get("semantic_document_id"),
                        "status": "consolidated",
                    }
                )
            except ValueError as exc:
                rejected.append(
                    {"candidate_id": candidate.get("candidate_id"), "reason": str(exc)}
                )
        qualia = self._publish_qualia_experience(
            run_ref,
            "stable_consolidation_review",
            "worker_stable_review",
            f"Revisión estable: {len(consolidated)} consolidados, {len(rejected)} rechazados.",
            proposed_learning="Solo consolidar cuando evidencia de uso acumulada demuestra valor real.",
        )
        return {
            "status": "completed",
            "consolidated": consolidated,
            "rejected": rejected,
            "stable_memory_written": bool(consolidated),
            "qualia": qualia,
        }

    def _learn_from_failure(
        self,
        run_ref: str,
        task: WorkerTask,
        status: str,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Convierte un fallo o un gate bajo en conocimiento candidato.

        F-018, aprobado por el operador el 2026-08-03. Hasta ahora un fallo se
        registraba en `worker_events` y ahí moría: el sistema volvía a
        equivocarse igual porque nada de lo aprendido sobrevivía al evento.

        El candidato entra como `candidate`, nunca como evidencia. Sólo
        `evidence_verified` y `stable` llegan al prompt, de modo que el saber se
        acumula hacia el umbral sin cambiar todavía lo que Tríade responde. Esa
        separación es la que impide que un error se convierta en doctrina por el
        mero hecho de haber ocurrido.
        """
        error = str(result.get("error") or result.get("reason") or "").strip()
        observation = f"La tarea {task.task_type} terminó en {status}."
        if error:
            observation += f" Motivo: {error[:400]}"
        return self._publish_qualia_experience(
            run_ref,
            task.task_type,
            "worker_failure",
            observation,
            extracted_pattern=json.dumps(
                {"task_type": task.task_type, "status": status, "error": error[:200]},
                ensure_ascii=False,
                sort_keys=True,
            ),
            # El candidato guarda el `proposed_learning` como contenido, no la
            # observación. Si la causa no viaja aquí, se pierde: quien evalúe
            # después leería «evitar que falle» sin saber por qué falló.
            proposed_learning=(
                f"Evitar que {task.task_type} vuelva a terminar en {status}."
                + (f" Causa observada: {error[:300]}" if error else "")
            ),
            # Un fallo es información de baja confianza: describe lo que pasó una
            # vez, no una regla. La confianza la tiene que ganar con evidencia.
            confidence=0.3,
            risk="medium",
            usefulness=0.6,
            ingest_learning=True,
        )

    def _system_debt_scan(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Mide la deuda estructural leyendo los grafos internos.

        Durante 600 ejecuciones esta tarea devolvió siempre la misma frase fija
        —"mantener vivo el ciclo observar→evaluar…"— sin escanear nada. Decía
        que había detectado deuda operacional y no había mirado el sistema.

        Ahora lee los grafos internos, que son los que sí recorren el
        repositorio y la base: tipos de tarea sin ejecutar, tablas que se
        escriben y nadie lee, módulos sin importador, entrypoints sin lanzador y
        eslabones de la cadena vital sin latido. El escaneo del AST se reutiliza
        mientras esté fresco; la parte que cambia entre ciclos se lee siempre.
        """
        from triade.observability.introspection import (
            build_debt_report,
            summarise_for_humans,
        )

        report = build_debt_report(
            Path(__file__).resolve().parents[2],
            db_path=Path(self.db_path),
        )
        content = summarise_for_humans(report)

        # Y si los órganos siguen cumpliendo su teoría operativa.
        #
        # `CoreAlignment` estaba escrito entero —comprueba por introspección real
        # del código que Central planifica, que el Hipotálamo regula, que la
        # Bodega persiste, que el Cristal compara y que el Runner cierra el
        # ciclo— y **no lo importaba nadie**: ni un módulo, ni un script, ni un
        # test. Un auditor de órganos que nunca se ejecuta no audita nada.
        #
        # Va aquí y no en `HealthSensors` porque mide estructura, no estado: el
        # resultado sólo cambia cuando cambia el código, así que correrlo en
        # cada ciclo metabólico sería gastar por gastar. La deuda estructural se
        # escanea unas 150 veces al día y ése es su sitio.
        alignment: dict[str, Any] = {}
        try:
            from triade.core.alignment import CoreAlignment

            alignment = CoreAlignment().evaluate_static_core()
        except (ImportError, OSError, RuntimeError, ValueError, TypeError) as exc:
            alignment = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        organos_flojos = [
            f"{o['organ']}: {'; '.join(o['missing'])}"
            for o in alignment.get("organs", [])
            if o.get("missing")
        ]
        if organos_flojos:
            content = f"{content} · órganos con capacidades sin cumplir: " + " · ".join(
                organos_flojos
            )
        qualia = self._publish_qualia_experience(
            run_ref,
            "system_debt_scan",
            "worker_debt",
            content,
            extracted_pattern=json.dumps(
                {
                    name: entry["count"]
                    for name, entry in report.get("items", {}).items()
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            proposed_learning=(
                "Reducir la deuda estructural medida en los grafos internos."
                if report.get("debt_items_total")
                else ""
            ),
            # F-018, aprobado por el operador el 2026-08-03: la deuda medida sí
            # genera conocimiento. Entra como `candidate`, no como evidencia:
            # sólo `evidence_verified` y `stable` llegan al prompt, así que el
            # saber se acumula hacia el umbral sin influir todavía en lo que
            # Tríade responde. Una deuda de 0 no enseña nada y no se ingesta.
            ingest_learning=bool(report.get("debt_items_total")),
        )
        return {
            "status": "observed",
            "observation": content,
            "debt": report,
            "core_alignment": alignment,
            "learning_candidate": None,
            "truth": "worker_self_observation_not_learning_evidence",
            "qualia": qualia,
        }

    def _bodega_global_review(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Revisa memoria reciente, learning_queue y stable_audit sin modificar identity_core.

        Produce un evento worker y experiencia Qualia. No consolida memoria
        automáticamente y no modifica identity_core.
        """
        from triade.core.bodega_global_context import build_bodega_global_context

        query = str(task.payload.get("query") or "revisión global de memoria")
        bodega_ctx = build_bodega_global_context(
            user_input=query,
            db_path=self.db_path,
            runs_dir=self.runs_dir,
            limit=10,
            semantic_recall_enabled=True,
        )

        episodes_count = len(bodega_ctx.get("recent_episodes") or [])
        learning = bodega_ctx.get("learning_context") or {}
        candidates_count = learning.get("candidates", 0)
        verified_count = learning.get("verified", 0)
        stable_audit = bodega_ctx.get("stable_audit_summary") or {}
        needs_review = stable_audit.get("stable_needs_review", 0)
        mem_conf = bodega_ctx.get("memory_confidence", "low")
        contradictions = bodega_ctx.get("contradictions") or []

        summary = (
            f"Revisión bodega global: confianza={mem_conf}, "
            f"episodios={episodes_count}, candidatos={candidates_count}, "
            f"verificados={verified_count}, stable_needs_review={needs_review}, "
            f"contradicciones={len(contradictions)}."
        )

        qualia = self._publish_qualia_experience(
            run_ref,
            "bodega_global_review",
            "worker_bodega_global",
            summary,
            extracted_pattern=str(
                {
                    "memory_confidence": mem_conf,
                    "episodes_count": episodes_count,
                    "candidates_count": candidates_count,
                    "verified_count": verified_count,
                    "stable_needs_review": needs_review,
                    "contradictions_count": len(contradictions),
                }
            )[:1000],
            proposed_learning="Mantener bodega global como base viva de contexto sin consolidar memoria automáticamente.",
        )

        return {
            "status": "completed",
            "memory_confidence": mem_conf,
            "episodes_count": episodes_count,
            "candidates_count": candidates_count,
            "verified_count": verified_count,
            "stable_needs_review": needs_review,
            "contradictions_count": len(contradictions),
            "stable_memory_written": False,
            "identity_core_modified": False,
            "qualia": qualia,
        }

    def _sandbox_snapshot_and_backup(
        self, watch_dir: Path, run_ref: str
    ) -> tuple[dict[str, str], dict[str, Path], Path]:
        """Snapshot de hashes + copia de respaldo de un directorio acotado.

        Usa AutonomousSandbox.create_snapshot() (T-0xx, hasta ahora sin
        conectar a producción) para los hashes; la copia de respaldo permite
        una reversión real por contenido, no solo detección de cambio.
        """
        from triade.core.autonomous_sandbox import AutonomousSandbox

        sandbox = AutonomousSandbox(db_path=self.db_path, runs_dir=self.runs_dir)
        existing_files = [f for f in watch_dir.rglob("*") if f.is_file()]
        snapshot = sandbox.create_snapshot(existing_files)
        backup_dir = self.runs_dir / f"shell_backup_{run_ref}_{int(time.time() * 1000)}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_map: dict[str, Path] = {}
        for f in existing_files:
            dest = backup_dir / f.relative_to(watch_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            backup_map[str(f.resolve())] = dest
        return snapshot, backup_map, backup_dir

    def _sandbox_restore(
        self,
        watch_dir: Path,
        snapshot_before: dict[str, str],
        backup_map: dict[str, Path],
    ) -> int:
        """Restaura contenido original y elimina archivos creados durante la falla."""
        restored = 0
        for fp, backup_path in backup_map.items():
            if backup_path.exists():
                target = Path(fp)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, target)
                restored += 1
        for f in watch_dir.rglob("*"):
            if f.is_file() and str(f.resolve()) not in snapshot_before:
                f.unlink(missing_ok=True)
        return restored

    def _shell_execute(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        """Ejecuta un comando shell autónomo con gating de autonomía y audit.

        Payload esperado: {command_key, autonomy_level?, timeout?, working_dir?}
        El resultado se registra como evidencia para neuronas.

        Si se pasa working_dir explícito (nunca el PROJECT_ROOT por defecto —
        sería costoso hashear todo el repo y no aporta nada, el comando ya
        está gobernado por su propia whitelist), se toma snapshot+backup
        antes y se compara después. Si el comando falló Y quedaron cambios,
        se revierte automáticamente por contenido (no solo se detecta). Un
        comando exitoso nunca se toca — esto es una red de seguridad
        adicional para fallas, no un cambio de comportamiento.
        """
        from triade.core.safe_shell import run_autonomous

        payload = task.payload if isinstance(task.payload, dict) else {}
        command_key = str(payload.get("command_key", ""))
        if not command_key:
            return {"status": "error", "error": "command_key requerido en payload."}

        autonomy_level = str(payload.get("autonomy_level", "observe_only"))
        timeout = int(payload.get("timeout", 60))
        working_dir = payload.get("working_dir")

        watch_dir: Path | None = None
        snapshot_before: dict[str, str] = {}
        backup_map: dict[str, Path] = {}
        backup_dir: Path | None = None
        if working_dir:
            try:
                candidate = Path(working_dir).resolve()
                if candidate.is_dir():
                    watch_dir = candidate
                    snapshot_before, backup_map, backup_dir = (
                        self._sandbox_snapshot_and_backup(watch_dir, run_ref)
                    )
            except OSError as exc:
                record_internal_error(
                    "worker_loop.sandbox_snapshot",
                    exc,
                    run_id=run_ref,
                    task_id=_integer_task_id(task.id),
                    payload={"module": __name__, "function": "_shell_execute"},
                    db_path=self.db_path,
                )
                watch_dir = None

        result = run_autonomous(
            command_key=command_key,
            timeout=timeout,
            autonomy_level=autonomy_level,
            source="worker",
            working_dir=working_dir,
        )

        if watch_dir is not None:
            try:
                from triade.core.autonomous_sandbox import AutonomousSandbox

                sandbox = AutonomousSandbox(
                    db_path=self.db_path, runs_dir=self.runs_dir
                )
                current_files = [f for f in watch_dir.rglob("*") if f.is_file()]
                snapshot_after = sandbox.create_snapshot(current_files)
                changed = sorted(
                    fp
                    for fp in set(snapshot_before) | set(snapshot_after)
                    if snapshot_before.get(fp) != snapshot_after.get(fp)
                )
                result["sandbox_file_changes"] = changed
                if result.get("status") != "ok" and changed:
                    restored = self._sandbox_restore(
                        watch_dir, snapshot_before, backup_map
                    )
                    result["sandbox_rollback"] = {
                        "performed": True,
                        "restored_files": restored,
                    }
            except OSError as exc:
                result["sandbox_rollback_error"] = str(exc)
                record_internal_error(
                    "worker_loop.sandbox_restore",
                    exc,
                    run_id=run_ref,
                    task_id=_integer_task_id(task.id),
                    payload={"module": __name__, "function": "_shell_execute"},
                    db_path=self.db_path,
                )
            finally:
                if backup_dir is not None:
                    shutil.rmtree(backup_dir, ignore_errors=True)

        # Registrar como evidencia si fue exitoso.
        if result.get("status") == "ok":
            try:
                from triade.services.event_bus import publish_event

                publish_event(
                    "shell_command_executed",
                    "worker_shell",
                    {
                        "command_key": command_key,
                        "returncode": result.get("returncode"),
                        "duration_ms": result.get("duration_ms"),
                        "stdout_preview": (result.get("stdout") or "")[:200],
                    },
                    db_path=self.db_path,
                    run_ref=run_ref,
                )
            except WORKER_OPERATION_ERRORS as exc:
                record_internal_error(
                    "worker_loop.shell_event",
                    exc,
                    run_id=run_ref,
                    task_id=_integer_task_id(task.id),
                    payload={
                        "module": __name__,
                        "function": "_shell_execute",
                        "operation": "publish_shell_execution_event",
                    },
                    db_path=self.db_path,
                )

        return result

    def _goal_safe_command(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        return self._shell_execute(task, run_ref, task_dir, config)

    def _goal_research(
        self, task: WorkerTask, run_ref: str, task_dir: Path, config: WorkerRunConfig
    ) -> dict[str, Any]:
        from triade.core.guarded_web import guarded_web_research
        from triade.research.governed import GovernedResearchWorker

        request = str(task.payload.get("request") or "").strip()
        if not request:
            return {"status": "error", "error": "request requerido"}
        allowed_sources = [
            str(item).strip()
            for item in task.payload.get("allowed_sources", [])
            if str(item).strip()
        ]
        if not allowed_sources:
            return {
                "status": "blocked",
                "reason": "goal_research requires explicit allowed_sources",
            }

        from triade.research.claim_distiller import distill_claims

        extractor = str(task.payload.get("claim_extractor") or "both").strip().lower()

        def provider(question: str, minimum: int) -> dict[str, Any]:
            result = guarded_web_research(question, max_sources=max(3, minimum))
            # Sin `claims`, `GovernedResearchWorker` cae en `unverifiable` y no
            # ingiere nada: 153 ejecuciones así en producción hasta el
            # 2026-08-09, todas sin candidato. El proveedor devolvía la
            # transcripción cruda y nadie la convertía en afirmación.
            client, modelo = self._claim_model_client(task, run_ref)
            fuentes = []
            for source in result.get("sources", []):
                texto = str(source.get("content") or source.get("excerpt") or "")
                fuentes.append(
                    {
                        **source,
                        "claims": distill_claims(
                            texto,
                            question=question,
                            extractor=extractor,
                            client=client,
                            model=modelo or "qwen3:1.7b",
                        ),
                    }
                )
            return {"sources": fuentes, "failures": result.get("failures", [])}

        trigger = (
            "human_decision"
            if task.payload.get("human_approved")
            else "benchmark_need"
            if task.payload.get("benchmark_need")
            else "gap"
        )
        resultado = GovernedResearchWorker(self.db_path, provider).run(
            question=request,
            trigger=trigger,
            scope=str(task.payload.get("scope") or "goal_research"),
            allowed_sources=allowed_sources,
            minimum_independent_sources=max(
                2, int(task.payload.get("minimum_independent_sources") or 2)
            ),
        )
        receipt = self._research_effect_receipt(resultado)
        if receipt is not None:
            resultado["effect_receipt"] = receipt.model_dump(mode="json")
        return resultado

    def _research_effect_receipt(self, resultado: dict[str, Any]) -> Any:
        """Recibo del candidato creado, con la poscondición **comprobada**.

        `candidate_created` declara un efecto, y un handler que declara efecto
        sin recibo se rechaza con `verified_effect_receipt_missing`. Nunca había
        saltado porque la investigación jamás llegó a crear un candidato: 156
        runs seguidos en `unverifiable`, que no declara efecto ninguno. El
        primero que sí lo creó —2026-08-09 02:04— murió aquí con el candidato
        ya escrito en `learning_queue`.

        El recibo no se firma por haber intentado la escritura: se relee la fila
        en la base y `verified` sale de que exista de verdad. Un recibo que se
        limitara a repetir lo que dijo el handler no verificaría nada.
        """
        from triade.runtime.effect_receipt import EffectReceipt

        candidate_id = str(resultado.get("candidate_id") or "")
        if not candidate_id:
            return None
        try:
            with sqlite3.connect(self.db_path) as conn:
                fila = conn.execute(
                    "SELECT status FROM learning_queue WHERE candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
        except sqlite3.Error:
            fila = None
        existe = fila is not None
        return EffectReceipt(
            action="create_learning_candidate",
            target=f"learning_queue:{candidate_id}",
            precondition={
                "minimum_independent_sources": resultado.get(
                    "minimum_independent_sources"
                ),
                "prior_failures": resultado.get("prior_failures"),
            },
            execution={
                "research_id": resultado.get("research_id"),
                "status": resultado.get("status"),
                "source_count": len(resultado.get("sources") or []),
                "claim_count": len(resultado.get("claims") or []),
            },
            postcondition={
                "passed": existe,
                "row_exists": existe,
                "candidate_status": (str(fila[0]) if fila else None),
            },
            verified=existe,
            verifier="learning_queue_row_verifier",
            evidence_refs=[
                f"governed_research_runs:{resultado.get('research_id')}",
                f"learning_queue:{candidate_id}",
            ],
            # El candidato entra como `candidate`: no influye en nada hasta que
            # el pipeline lo promueva, así que revertirlo no es obligatorio.
            rollback_ref=f"learning_queue:{candidate_id}",
        )

    def _observable_ollama_client(
        self,
        task: WorkerTask,
        run_ref: str,
        *,
        cognitive_function: str,
        artifact: str,
        consumer: str,
    ) -> Any:
        """Cliente de worker con evidencia causal segura y correlacionable."""
        from triade.models.ollama_client import OllamaClient
        from triade.services.event_bus import publish_event

        task_id = _integer_task_id(task.id)

        def observe(model_event: dict[str, Any]) -> None:
            payload = {
                **model_event,
                "task_id": str(task.id) if task.id is not None else None,
                "run_ref": run_ref,
                "worker": "living_worker",
                "cognitive_function": cognitive_function,
                "artifact": artifact,
                "consumer": consumer,
                "effect": "available_to_task_handler"
                if model_event.get("ok")
                else "none",
            }
            publish_event(
                "ollama_call_completed",
                "worker_loop",
                payload,
                severity="info" if model_event.get("ok") else "error",
                db_path=self.db_path,
                run_ref=run_ref,
                task_id=task_id,
                task_type=task.task_type,
            )

        return OllamaClient(event_callback=observe)

    def _claim_model_client(self, task: WorkerTask, run_ref: str) -> tuple[Any, str]:
        """Sangre cognitiva para destilar, si la política del rol la concede.

        Destilar afirmaciones **es** una evaluación de aprendizaje, así que se
        pide por su rol —`learning_evaluation`— en vez de instanciar un cliente
        a ciegas. Dos cosas se ganan con eso: el modelo lo elige Ollama Blood
        entre los que de verdad están instalados, en lugar de un nombre fijo que
        puede no existir; y cuando la sangre está baja el destilador lo sabe
        antes de intentarlo y se queda en reglas, en vez de gastar una llamada
        que va a fallar.

        `(None, "")` no rompe nada: `distill_claims` cae a reglas. Investigar con
        menos cobertura es mejor que no investigar.
        """
        try:
            from triade.core.ollama_blood import check_ollama_blood, ollama_blood_policy

            sangre = check_ollama_blood()
            politica = ollama_blood_policy("learning_evaluation", sangre)
            modelo = str(politica.get("model_used") or "")
            if not politica.get("allowed") or not modelo:
                return None, ""
            return (
                self._observable_ollama_client(
                    task,
                    run_ref,
                    cognitive_function="learning_evaluation",
                    artifact="distilled_claims",
                    consumer="GovernedResearchWorker",
                ),
                modelo,
            )
        except (ImportError, OSError, RuntimeError, KeyError, TypeError):
            return None, ""

    def _artifact_dir(self, run_ref: str) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return self.runs_dir / f"{stamp}-{run_ref[-8:]}"
