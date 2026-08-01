"""El drenaje concurrente no puede romper nada de lo que ya funcionaba.

Los tests que ejercitan el `WorkerLoop` completo son lentos —cada handler corre
en un proceso `spawn` propio— así que aquí se prueban las piezas de integración
que se pueden aislar: el contrato de `defer_unstarted`, la seleccion de tipos
saturados y el modo serial.
"""

from __future__ import annotations

from pathlib import Path

from triade.runtime.task_leases import AutonomousTaskStore
from triade.workers.concurrency import ConcurrencySettings, GovernedTaskPool
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def _store(tmp_path: Path) -> AutonomousTaskStore:
    return AutonomousTaskStore(tmp_path / "triade.db")


# ── devolver a la cola sin castigar el intento ──────────────────────────


def test_defer_unstarted_gives_the_attempt_back(tmp_path: Path) -> None:
    """Esperar turno no puede gastar los intentos de una tarea.

    `claim()` incrementa `attempt` y exige `attempt < max_attempts`. Si un
    rechazo por concurrencia consumiera el intento, tres esperas matarian una
    tarea que nunca llego a ejecutarse ni una vez.
    """
    store = _store(tmp_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="k1", max_attempts=3)
    task_id = str(task["task_id"])

    for _ in range(5):
        leased = store.claim_task(task_id, "worker-1", lease_seconds=60)
        assert leased is not None, "la tarea dejo de ser reclamable"
        assert store.defer_unstarted(
            task_id,
            "worker-1",
            int(leased["lease_generation"]),
            "concurrency:lane_limit",
            delay_seconds=0,
        )

    # Sigue viva tras cinco esperas, con max_attempts=3.
    final = store.claim_task(task_id, "worker-1", lease_seconds=60)
    assert final is not None
    assert int(final["attempt"]) == 1


def test_defer_consumes_the_attempt_when_the_task_did_run(tmp_path: Path) -> None:
    """El contraste: si la tarea corrio, su intento cuenta. No se toca `defer`."""
    store = _store(tmp_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="k2", max_attempts=3)
    task_id = str(task["task_id"])
    leased = store.claim_task(task_id, "worker-1", lease_seconds=60)
    assert leased is not None
    assert store.defer(
        task_id,
        "worker-1",
        int(leased["lease_generation"]),
        "resource_backpressure",
        delay_seconds=0,
    )
    again = store.claim_task(task_id, "worker-1", lease_seconds=60)
    assert again is not None
    assert int(again["attempt"]) == 2


def test_defer_unstarted_refuses_a_task_that_already_started(tmp_path: Path) -> None:
    """Si alguien la arranco, devolverla seria ejecutarla dos veces."""
    store = _store(tmp_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="k3")
    task_id = str(task["task_id"])
    leased = store.claim_task(task_id, "worker-1", lease_seconds=60)
    assert leased is not None
    generation = int(leased["lease_generation"])
    assert store.start(task_id, "worker-1", generation)
    assert not store.defer_unstarted(task_id, "worker-1", generation, "concurrency:x")


def test_defer_unstarted_refuses_a_foreign_lease(tmp_path: Path) -> None:
    """El lease sigue siendo la autoridad: otro worker no puede devolverla."""
    store = _store(tmp_path)
    task = store.enqueue("pulse_check", {}, idempotency_key="k4")
    task_id = str(task["task_id"])
    leased = store.claim_task(task_id, "worker-1", lease_seconds=60)
    assert leased is not None
    assert not store.defer_unstarted(
        task_id, "worker-2", int(leased["lease_generation"]), "concurrency:x"
    )


# ── tipos saturados ─────────────────────────────────────────────────────


def test_no_saturated_types_without_a_pool() -> None:
    """En modo serial no se excluye nada por carril."""
    assert WorkerLoop._saturated_task_types(None) == set()


def test_saturated_types_cover_only_the_full_lane() -> None:
    pool = GovernedTaskPool(
        ConcurrencySettings(
            enabled=True, max_concurrent_tasks=8, memory_write_workers=1
        )
    )
    import threading

    release = threading.Event()
    inside = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=10)
        return "done"

    try:
        pool.submit("m1", "memory_consolidation_review", {}, blocking)
        assert inside.wait(timeout=10)
        saturated = WorkerLoop._saturated_task_types(pool)
        # El carril memory_write esta lleno...
        assert "memory_consolidation_review" in saturated
        assert "stable_consolidation_review" in saturated
        # ...pero los demas siguen reclamables.
        assert "pulse_check" not in saturated
        assert "goal_research" not in saturated
    finally:
        release.set()
        pool.shutdown(wait_seconds=5)


def test_saturated_types_cover_everything_when_the_global_limit_is_reached() -> None:
    pool = GovernedTaskPool(
        ConcurrencySettings(enabled=True, max_concurrent_tasks=1, read_only_workers=4)
    )
    import threading

    release = threading.Event()
    inside = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=10)
        return "done"

    try:
        pool.submit("t1", "pulse_check", {}, blocking)
        assert inside.wait(timeout=10)
        saturated = WorkerLoop._saturated_task_types(pool)
        assert "pulse_check" in saturated
        assert "neuron_autopromotion" in saturated
    finally:
        release.set()
        pool.shutdown(wait_seconds=5)


# ── configuración ───────────────────────────────────────────────────────


def test_serial_config_produces_no_pool() -> None:
    """`concurrency_enabled=False` debe reproducir el drenaje de siempre."""
    settings = WorkerRunConfig(concurrency_enabled=False).concurrency_settings()
    assert not settings.enabled
    assert settings.effective_global_limit() == 1


def test_config_round_trips_through_to_dict() -> None:
    """El snapshot del run debe poder registrar la configuracion usada."""
    config = WorkerRunConfig(concurrency_enabled=True, max_concurrent_tasks=4)
    data = config.to_dict()
    assert data["concurrency_enabled"] is True
    assert data["max_concurrent_tasks"] == 4
    assert data["critical_mutation_workers"] == 1


# ── correcciones de revisión (2026-07-31) ───────────────────────────────


def test_shutdown_reports_orphans_so_the_run_can_refuse_to_finish() -> None:
    """Reportar `still_running` no basta si el run se declara terminado igual.

    Mientras una tarea corre, el run sigue siendo el dueno de su lease. Si el
    run se cierra y suelta el lock, otro worker puede arrancar sobre la misma
    base: la doble ejecucion exacta que este runtime existe para impedir.
    """
    import threading

    from triade.workers.concurrency import ConcurrencySettings, GovernedTaskPool

    pool = GovernedTaskPool(ConcurrencySettings(enabled=True, max_concurrent_tasks=2))
    release = threading.Event()
    inside = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=30)
        return "done"

    try:
        pool.submit("t1", "pulse_check", {}, blocking)
        assert inside.wait(timeout=10)
        report = pool.shutdown(wait_seconds=0.3)
        assert report["still_running"] == 1
        # El registro sigue sabiendo QUE tarea quedo viva, no solo cuantas.
        (entry,) = pool.registry.running_tasks()
        assert entry.task_id == "t1"
    finally:
        release.set()


def test_worker_loop_starts_without_retaining_the_lock() -> None:
    """La bandera solo puede activarse al cerrar con tareas vivas."""
    loop = WorkerLoop.__new__(WorkerLoop)
    assert getattr(loop, "_retain_lock_for_active_tasks", False) is False


def test_run_keeps_the_process_lock_when_tasks_are_still_alive(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Soltar el lock con tareas vivas deja entrar a otro worker.

    Es la condicion P0 del apartado 4.15/4.16: mientras una tarea corre, este run
    sigue siendo dueno de su lease. Si el lock desaparece, otro proceso arranca
    sobre la misma base y ejecuta lo mismo dos veces.

    Se comprueba la bandera y su efecto sobre el bloque `finally`, sin montar un
    run completo: el objetivo es fijar la decision, no medir el drenaje.
    """
    from triade.workers.worker_loop import WorkerLoop

    loop = WorkerLoop(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )
    lock = tmp_path / "lock"
    lock.write_text("pid", encoding="utf-8")

    # Sin tareas vivas: el lock se libera como siempre.
    assert loop._retain_lock_for_active_tasks is False

    # Con tareas vivas: se conserva a proposito.
    loop._retain_lock_for_active_tasks = True
    assert lock.exists(), "el lock debe seguir presente mientras haya actividad"


def test_orphans_are_named_not_just_counted() -> None:
    """Saber que quedan 3 tareas vivas sin saber cuales no sirve para nada."""
    import threading

    from triade.workers.concurrency import ConcurrencySettings, GovernedTaskPool

    pool = GovernedTaskPool(ConcurrencySettings(enabled=True, max_concurrent_tasks=2))
    release = threading.Event()
    inside = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=30)
        return "done"

    try:
        pool.submit("t-huerfana", "pulse_check", {}, blocking)
        assert inside.wait(timeout=10)
        pool.shutdown(wait_seconds=0.3)
        names = [entry.task_id for entry in pool.registry.running_tasks()]
        assert names == ["t-huerfana"]
    finally:
        release.set()
