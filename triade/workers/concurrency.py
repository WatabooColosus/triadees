"""Concurrencia gobernada para los Living Workers.

Hasta ahora `WorkerLoop.drain_queue()` reclamaba una tarea, la ejecutaba entera y
solo entonces reclamaba la siguiente. `max_tasks_per_drain` nunca significó
paralelismo: era un presupuesto de cuántas tareas atender **en fila** por ciclo.
El efecto práctico es que una sola investigación lenta contra Ollama bloqueaba
revisiones que no escriben nada.

Este módulo aporta la decisión —**qué puede solaparse y qué no**— aislada del
`WorkerLoop`, para que la respuesta viva en un solo sitio auditable en vez de
dispersarse en `if task_type == ...`.

Qué NO hace, deliberadamente
----------------------------
- No reclama tareas: el lease v2 (`AutonomousTaskStore`) sigue siendo la única
  autoridad de propiedad. Aquí solo se decide si una tarea **ya arrendada** puede
  arrancar ahora o debe esperar.
- No cierra tareas: el cierre atómico sigue siendo de `_execute_autonomous_task`.
- No sustituye al scheduler ni crea otra cola.

Modelo de admisión
------------------
Una tarea entra a ejecutarse solo si se cumplen **las tres** condiciones:

1. hay hueco en el límite global;
2. hay hueco en el límite de su carril;
3. ninguna de sus claves de exclusión está tomada por otra tarea viva.

Las claves de exclusión son lo que impide que dos tareas muten a la vez la misma
candidata, la misma neurona o la misma versión estable. Sin ellas, "paralelizar
evaluaciones" significaría dos sandboxes pisándose sobre el mismo candidato.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

LaneName = Literal[
    "read_only",
    "research",
    "evaluation",
    "memory_write",
    "critical_mutation",
]

#: Orden estable para snapshots y documentación.
LANE_ORDER: tuple[LaneName, ...] = (
    "read_only",
    "research",
    "evaluation",
    "memory_write",
    "critical_mutation",
)

#: Carril al que cae cualquier tarea sin política declarada.
#:
#: Es el carril serial global, no un carril nuevo: una tarea desconocida podría
#: escribir cualquier cosa, así que se la trata como mutación crítica hasta que
#: alguien declare su política. Preferimos frenar de más a corromper estado.
UNKNOWN_TASK_LANE: LaneName = "critical_mutation"

ResourceClass = Literal["light", "io", "model", "critical"]


@dataclass(frozen=True, slots=True)
class TaskConcurrencyPolicy:
    """Cómo puede solaparse un tipo de tarea concreto."""

    lane: LaneName
    max_concurrency: int
    resource_class: ResourceClass
    exclusive_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency debe ser >= 1")


#: Clave de exclusión que no se lee del payload: la toma **toda** tarea del tipo
#: que la declara, de modo que dos promociones nunca coexisten aunque sean de
#: neuronas distintas.
GLOBAL_PROMOTION_KEY = "global_promotion"

_GLOBAL_KEYS = frozenset({GLOBAL_PROMOTION_KEY})


#: Política declarativa. **Todo** tipo conocido debe aparecer aquí; el test
#: `test_every_known_task_type_has_a_policy` falla si alguien añade un tipo y
#: olvida clasificarlo.
TASK_CONCURRENCY_POLICY: dict[str, TaskConcurrencyPolicy] = {
    # ── read_only: observan y reportan, no escriben estado estable ──────
    "pulse_check": TaskConcurrencyPolicy("read_only", 4, "light"),
    # Estuvo en `read_only` con concurrencia 4 y sin clave de exclusión, y eso
    # era sencillamente falso: `_pending_learning_review` hace `pipe.evaluate()`
    # y `pipe.verify()`, o sea lee, decide y **escribe** sobre las mismas filas
    # de la cola de aprendizaje.
    #
    # Esa clasificación es la causa del fallo que tuvo la concurrencia apagada
    # durante semanas. Dos obreros listaban el mismo candidato, uno lo movía y
    # el otro se estrellaba:
    #
    #     worker_0: list_candidates(status='evaluated') -> [X]
    #     worker_1: list_candidates(status='evaluated') -> [X]
    #     worker_0: verify(X)  -> X pasa a 'internally_checked'
    #     worker_1: verify(X)  -> ValueError: Solo se verifica un candidato en
    #                             estado 'evaluated' (actual: internally_checked)
    #
    # No sirve una clave de exclusión por candidato: el handler **no recibe** un
    # candidato, se los busca él. Lo que toca es que sea serial, igual que
    # `learning_candidate_deduplication`, que tiene la misma forma.
    "pending_learning_review": TaskConcurrencyPolicy("memory_write", 1, "light"),
    # Extraer una proposición de un run es barato y no escribe estado estable
    # más allá de la cola de candidatos.
    "learning_candidate_generation": TaskConcurrencyPolicy(
        "memory_write", 1, "light", ("source_run_id",)
    ),
    # La deduplicación toca `learning_candidate_groups`: serial, o dos obreros
    # crearían dos canónicos para el mismo texto.
    "learning_candidate_deduplication": TaskConcurrencyPolicy(
        "memory_write", 1, "light"
    ),
    # La evidencia gasta inferencias: una por candidato, y pocas a la vez.
    "learning_evidence_generation": TaskConcurrencyPolicy(
        "evaluation", 1, "model", ("candidate_id",)
    ),
    "federation_inbox_review": TaskConcurrencyPolicy("read_only", 4, "io"),
    "system_debt_scan": TaskConcurrencyPolicy("read_only", 4, "light"),
    "bodega_global_review": TaskConcurrencyPolicy("read_only", 4, "light"),
    # ── research: consultan modelos o la web; caras y lentas ────────────
    "goal_research": TaskConcurrencyPolicy("research", 2, "model"),
    "research_curriculum": TaskConcurrencyPolicy("research", 2, "model"),
    "neuron_candidate_formation": TaskConcurrencyPolicy(
        "research", 2, "model", ("neuron_id",)
    ),
    # ── evaluation: sandbox, medición y gates por candidata ─────────────
    "experimental_neuron_activity": TaskConcurrencyPolicy(
        "evaluation", 2, "model", ("neuron_id",)
    ),
    "neuron_education_cycle": TaskConcurrencyPolicy(
        "evaluation", 2, "model", ("neuron_id",)
    ),
    "self_improvement_evaluation": TaskConcurrencyPolicy(
        "evaluation", 2, "model", ("candidate_id", "neuron_id", "proposal_id")
    ),
    "self_improvement_canary_observation": TaskConcurrencyPolicy(
        "evaluation", 2, "light", ("candidate_id", "canary_id")
    ),
    # ── memory_write: escriben memoria gobernada; serial ────────────────
    "memory_consolidation_review": TaskConcurrencyPolicy("memory_write", 1, "light"),
    "stable_consolidation_review": TaskConcurrencyPolicy("memory_write", 1, "light"),
    "semantic_memory_governance": TaskConcurrencyPolicy("memory_write", 1, "light"),
    "encrypted_backup": TaskConcurrencyPolicy("memory_write", 1, "io"),
    # Escribe ficheros en disco vía GovernedFileWriteCapability. Estuvo
    # clasificada como `read_only` con concurrencia 4, que era sencillamente
    # falso: cuatro escrituras simultáneas podían apuntar al mismo `target`.
    # La clave de exclusión por `target` cubre además el caso de dos escrituras
    # al mismo fichero desde carriles distintos.
    "write_governed_text_artifact": TaskConcurrencyPolicy(
        "memory_write", 1, "io", ("target",)
    ),
    # ── critical_mutation: cambian lo estable; serial global ────────────
    "neuron_autopromotion": TaskConcurrencyPolicy(
        "critical_mutation", 1, "critical", ("neuron_id", GLOBAL_PROMOTION_KEY)
    ),
    "goal_lora_train": TaskConcurrencyPolicy(
        "critical_mutation", 1, "critical", ("neuron_id",)
    ),
    "goal_install": TaskConcurrencyPolicy("critical_mutation", 1, "critical"),
    # Ejecuta un comando de shell: puede tocar cualquier cosa del sistema.
    "goal_safe_command": TaskConcurrencyPolicy("critical_mutation", 1, "critical"),
}

#: Política aplicada a tipos no declarados: serial y ruidosa.
FALLBACK_POLICY = TaskConcurrencyPolicy(UNKNOWN_TASK_LANE, 1, "critical")


def policy_for(task_type: str) -> TaskConcurrencyPolicy:
    """Devuelve la política del tipo, o la serial segura si no está declarada."""
    policy = TASK_CONCURRENCY_POLICY.get(task_type)
    if policy is None:
        logger.warning(
            "tipo de tarea sin politica de concurrencia declarada: %r; "
            "se ejecuta en serie en el carril %s",
            task_type,
            UNKNOWN_TASK_LANE,
        )
        return FALLBACK_POLICY
    return policy


def is_known_task_type(task_type: str) -> bool:
    return task_type in TASK_CONCURRENCY_POLICY


def exclusion_keys(task_type: str, payload: dict[str, Any] | None) -> frozenset[str]:
    """Claves que esta tarea debe tomar en exclusiva mientras corre.

    Una clave se resuelve contra el payload (`neuron_id` → `neuron_id=n-7`) salvo
    las globales, que se toman por el mero hecho de declararlas. Si el payload no
    trae el valor, la clave **no** se toma: no se puede excluir por algo que no
    identifica a nada. Eso es correcto, no una fuga: sin `candidate_id` la tarea
    no está mutando ninguna candidata concreta.
    """
    policy = policy_for(task_type)
    data = payload or {}
    keys: set[str] = set()
    for name in policy.exclusive_keys:
        if name in _GLOBAL_KEYS:
            keys.add(name)
            continue
        raw = data.get(name)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            keys.add(f"{name}={value}")
    return frozenset(keys)


@dataclass(slots=True)
class ConcurrencySettings:
    """Límites configurables. Con `enabled=False` el worker corre como siempre."""

    enabled: bool = True
    max_concurrent_tasks: int = 4
    read_only_workers: int = 4
    research_workers: int = 2
    evaluation_workers: int = 2
    memory_write_workers: int = 1
    critical_mutation_workers: int = 1

    @classmethod
    def conservative(cls) -> ConcurrencySettings:
        """Activación inicial de la Fase 7: menos solapamiento, más margen."""
        return cls(
            enabled=True,
            max_concurrent_tasks=3,
            read_only_workers=2,
            research_workers=1,
            evaluation_workers=1,
            memory_write_workers=1,
            critical_mutation_workers=1,
        )

    @classmethod
    def serial(cls) -> ConcurrencySettings:
        """Equivalente exacto al comportamiento anterior a la concurrencia."""
        return cls(
            enabled=False,
            max_concurrent_tasks=1,
            read_only_workers=1,
            research_workers=1,
            evaluation_workers=1,
            memory_write_workers=1,
            critical_mutation_workers=1,
        )

    def lane_limit(self, lane: LaneName) -> int:
        limits: dict[LaneName, int] = {
            "read_only": self.read_only_workers,
            "research": self.research_workers,
            "evaluation": self.evaluation_workers,
            "memory_write": self.memory_write_workers,
            "critical_mutation": self.critical_mutation_workers,
        }
        return max(1, int(limits[lane]))

    def effective_global_limit(self) -> int:
        if not self.enabled:
            return 1
        return max(1, int(self.max_concurrent_tasks))


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """Por qué una tarea arrancó ahora, o por qué no."""

    admitted: bool
    lane: LaneName
    resource_class: ResourceClass
    keys: frozenset[str] = frozenset()
    reason: str = ""


@dataclass(slots=True)
class RunningTask:
    task_id: str
    task_type: str
    lane: LaneName
    resource_class: ResourceClass
    keys: frozenset[str]
    started_at: float
    thread_name: str = ""
    lease_generation: int = 0


@dataclass(slots=True)
class RunningTaskRegistry:
    """Contabilidad de lo que corre ahora mismo. Segura entre hilos.

    Es la pieza que hace verificable la promesa "dos tareas nunca mutan la misma
    candidata": la exclusión se comprueba y se toma **bajo el mismo lock** que la
    admisión, así que no hay ventana entre "compruebo que está libre" y "la tomo".
    """

    settings: ConcurrencySettings
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _running: dict[str, RunningTask] = field(default_factory=dict)
    _held_keys: dict[str, str] = field(default_factory=dict)
    _pressure_scale: float = 1.0

    # ── admisión ────────────────────────────────────────────────────────
    def try_admit(
        self,
        task_id: str,
        task_type: str,
        payload: dict[str, Any] | None = None,
        *,
        lease_generation: int = 0,
        now: float | None = None,
    ) -> AdmissionDecision:
        import time

        policy = policy_for(task_type)
        keys = exclusion_keys(task_type, payload)
        with self._lock:
            if task_id in self._running:
                return AdmissionDecision(
                    False, policy.lane, policy.resource_class, keys, "already_running"
                )
            if len(self._running) >= self._global_limit_locked():
                return AdmissionDecision(
                    False, policy.lane, policy.resource_class, keys, "global_limit"
                )
            if self._lane_running_locked(policy.lane) >= self._lane_limit_locked(
                policy.lane, policy.max_concurrency
            ):
                return AdmissionDecision(
                    False, policy.lane, policy.resource_class, keys, "lane_limit"
                )
            taken = keys & self._held_keys.keys()
            if taken:
                return AdmissionDecision(
                    False,
                    policy.lane,
                    policy.resource_class,
                    keys,
                    # `min` da un motivo estable cuando chocan varias claves.
                    f"exclusive_key_held:{min(taken)}",
                )
            self._running[task_id] = RunningTask(
                task_id=task_id,
                task_type=task_type,
                lane=policy.lane,
                resource_class=policy.resource_class,
                keys=keys,
                started_at=time.time() if now is None else now,
                lease_generation=lease_generation,
            )
            for key in keys:
                self._held_keys[key] = task_id
        return AdmissionDecision(
            True, policy.lane, policy.resource_class, keys, "admitted"
        )

    def release(self, task_id: str) -> RunningTask | None:
        with self._lock:
            entry = self._running.pop(task_id, None)
            if entry is None:
                return None
            for key in entry.keys:
                if self._held_keys.get(key) == task_id:
                    del self._held_keys[key]
            return entry

    def mark_thread(self, task_id: str, thread_name: str) -> None:
        with self._lock:
            entry = self._running.get(task_id)
            if entry is not None:
                entry.thread_name = thread_name

    # ── presión de recursos ─────────────────────────────────────────────
    def set_pressure_scale(self, scale: float) -> None:
        """Reduce los límites sin reconfigurar nada. 1.0 = límites nominales.

        El backpressure existente decide *si* una tarea puede entrar; esto decide
        *cuántas* caben a la vez. Son complementarios: con la GPU cargada
        queremos seguir atendiendo revisiones baratas, pero no dos
        investigaciones contra el mismo modelo local.
        """
        with self._lock:
            self._pressure_scale = min(1.0, max(0.0, float(scale)))

    @property
    def pressure_scale(self) -> float:
        with self._lock:
            return self._pressure_scale

    def _scaled(self, limit: int) -> int:
        return max(1, int(limit * self._pressure_scale)) if limit > 0 else 1

    def _global_limit_locked(self) -> int:
        return self._scaled(self.settings.effective_global_limit())

    def _lane_limit_locked(self, lane: LaneName, policy_limit: int) -> int:
        if not self.settings.enabled:
            return 1
        return self._scaled(min(self.settings.lane_limit(lane), policy_limit))

    def _lane_running_locked(self, lane: LaneName) -> int:
        return sum(1 for entry in self._running.values() if entry.lane == lane)

    # ── observabilidad ──────────────────────────────────────────────────
    def running_count(self) -> int:
        with self._lock:
            return len(self._running)

    def running_tasks(self) -> tuple[RunningTask, ...]:
        with self._lock:
            return tuple(self._running.values())

    def holds_key(self, key: str) -> bool:
        with self._lock:
            return key in self._held_keys

    def snapshot(self, *, queued: int = 0) -> dict[str, Any]:
        with self._lock:
            lanes: dict[str, dict[str, int]] = {}
            for lane in LANE_ORDER:
                lanes[lane] = {
                    "limit": (
                        1
                        if not self.settings.enabled
                        else self._scaled(self.settings.lane_limit(lane))
                    ),
                    "running": self._lane_running_locked(lane),
                }
            return {
                "enabled": self.settings.enabled,
                "global_limit": self._global_limit_locked(),
                "running": len(self._running),
                "queued": int(queued),
                "pressure_scale": self._pressure_scale,
                "lanes": lanes,
            }


class GovernedTaskPool:
    """Pool de hilos que solo acepta lo que el registro admite.

    Cada tarea se ejecuta en su propio hilo, y **cada store abre su conexión
    SQLite dentro de ese hilo** (`AutonomousTaskStore._connect()` ya lo hace por
    operación). No se comparte ninguna conexión creada en el hilo principal.
    """

    def __init__(
        self,
        settings: ConcurrencySettings,
        *,
        registry: RunningTaskRegistry | None = None,
        thread_name_prefix: str = "triade-worker",
    ) -> None:
        self.settings = settings
        self.registry = registry or RunningTaskRegistry(settings)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, settings.effective_global_limit()),
            thread_name_prefix=thread_name_prefix,
        )
        self._futures: dict[str, Future[Any]] = {}
        self._futures_lock = threading.Lock()
        self._accepting = True

    @property
    def accepting(self) -> bool:
        return self._accepting

    def submit(
        self,
        task_id: str,
        task_type: str,
        payload: dict[str, Any] | None,
        fn: Callable[[], Any],
        *,
        lease_generation: int = 0,
    ) -> AdmissionDecision:
        """Admite y despacha, o devuelve el motivo del rechazo sin ejecutar nada.

        Quien recibe un rechazo debe **devolver la tarea a la cola** (defer), no
        descartarla: el lease ya está tomado y perderlo en silencio dejaría la
        tarea colgada hasta que expire.
        """
        if not self._accepting:
            policy = policy_for(task_type)
            return AdmissionDecision(
                False,
                policy.lane,
                policy.resource_class,
                exclusion_keys(task_type, payload),
                "pool_closed",
            )
        decision = self.registry.try_admit(
            task_id, task_type, payload, lease_generation=lease_generation
        )
        if not decision.admitted:
            return decision

        def _runner() -> Any:
            self.registry.mark_thread(task_id, threading.current_thread().name)
            try:
                return fn()
            finally:
                self.registry.release(task_id)

        try:
            future = self._executor.submit(_runner)
        except RuntimeError:
            # El executor ya estaba cerrado: soltamos la reserva para no dejar
            # claves de exclusión tomadas por una tarea que nunca corrió.
            self.registry.release(task_id)
            return AdmissionDecision(
                False,
                decision.lane,
                decision.resource_class,
                decision.keys,
                "pool_closed",
            )
        with self._futures_lock:
            self._futures[task_id] = future
        return decision

    def collect_finished(self) -> list[tuple[str, Future[Any]]]:
        """Retira los futuros ya terminados. No bloquea."""
        with self._futures_lock:
            done = [(tid, fut) for tid, fut in self._futures.items() if fut.done()]
            for task_id, _ in done:
                self._futures.pop(task_id, None)
        return done

    def pending_count(self) -> int:
        with self._futures_lock:
            return len(self._futures)

    def wait_for_slot(self, timeout: float) -> None:
        """Espera acotada a que algo termine. Nunca espera a una tarea concreta."""
        from concurrent.futures import wait

        with self._futures_lock:
            pending = [fut for fut in self._futures.values() if not fut.done()]
        if pending and timeout > 0:
            wait(pending, timeout=timeout, return_when="FIRST_COMPLETED")

    def stop_accepting(self) -> None:
        self._accepting = False

    def shutdown(self, *, wait_seconds: float = 30.0) -> dict[str, Any]:
        """Deja de aceptar, espera un período acotado y reporta lo que siguió vivo.

        No cancela a la fuerza una tarea en vuelo ni la marca como terminada: una
        tarea todavía activa mantiene su lease, y el lease es la autoridad. Lo que
        no acabe a tiempo se reporta como `still_running` y será recuperado por
        expiración de lease, que es el mecanismo que ya existe para esto.
        """
        from concurrent.futures import wait

        self.stop_accepting()
        with self._futures_lock:
            pending = [fut for fut in self._futures.values() if not fut.done()]
        cancelled = 0
        if pending and wait_seconds > 0:
            _done, not_done = wait(pending, timeout=wait_seconds)
            for future in not_done:
                if future.cancel():
                    cancelled += 1
        self._executor.shutdown(wait=False)
        still_running = self.registry.running_count()
        return {
            "cancelled": cancelled,
            "still_running": still_running,
            "pending_futures": self.pending_count(),
        }

    def snapshot(self, *, queued: int = 0) -> dict[str, Any]:
        return self.registry.snapshot(queued=queued)
