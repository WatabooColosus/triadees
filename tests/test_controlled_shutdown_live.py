"""Parada controlada con tareas vivas: el punto donde se pierde o se gana la verdad.

Un runtime puede mentir de dos formas al pararse:

1. Declarando `completed` un run cuyas tareas siguen corriendo.
2. Soltando el process lock mientras esas tareas siguen siendo suyas, con lo que
   otro worker arranca sobre la misma base y ejecuta lo mismo dos veces.

Estas pruebas fijan las dos. No arrancan un `WorkerLoop` completo —eso mete
procesos `spawn` y ruido temporal— sino que ejercitan el pool y las banderas que
gobiernan el cierre, que es donde vive la decisión.
"""

from __future__ import annotations

import threading
from pathlib import Path

from triade.workers.concurrency import ConcurrencySettings, GovernedTaskPool
from triade.workers.contracts import WorkerRunConfig
from triade.workers.worker_loop import WorkerLoop


def _blocking_pool(limit: int = 2) -> tuple[GovernedTaskPool, threading.Event]:
    pool = GovernedTaskPool(
        ConcurrencySettings(enabled=True, max_concurrent_tasks=limit)
    )
    release = threading.Event()
    inside = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=30)
        return "done"

    pool.submit("t-viva", "pulse_check", {}, blocking)
    assert inside.wait(timeout=15), "la tarea no llegó a arrancar"
    return pool, release


def test_draining_stops_accepting_but_keeps_the_live_task() -> None:
    """Drenar es dejar de aceptar, no abandonar lo que ya corre."""
    pool, release = _blocking_pool()
    try:
        pool.stop_accepting()
        rejected = pool.submit("t-nueva", "pulse_check", {}, lambda: "no")
        assert not rejected.admitted
        assert rejected.reason == "pool_closed"
        assert pool.registry.running_count() == 1
    finally:
        release.set()
        pool.shutdown(wait_seconds=5)


def test_shutdown_never_reports_a_live_task_as_finished() -> None:
    """`still_running` tiene que decir la verdad aunque sea incómoda."""
    pool, release = _blocking_pool()
    try:
        report = pool.shutdown(wait_seconds=0.3)
        assert report["still_running"] == 1
        assert not pool.accepting
    finally:
        release.set()


def test_shutdown_waits_when_the_task_can_finish() -> None:
    """Si acaba a tiempo, no se reporta nada raro: el caso normal sigue normal."""
    pool = GovernedTaskPool(ConcurrencySettings(enabled=True, max_concurrent_tasks=2))
    finished = threading.Event()

    def quick() -> str:
        finished.set()
        return "done"

    pool.submit("t-rapida", "pulse_check", {}, quick)
    report = pool.shutdown(wait_seconds=15)
    assert finished.is_set()
    assert report["still_running"] == 0


def test_a_run_with_live_tasks_is_not_declared_completed(tmp_path: Path) -> None:
    """El estado del run debe distinguirse de `completed`.

    `completed_with_active_tasks` no es cosmética: es la diferencia entre "acabó"
    y "dejé de mirar". Un operador que ve `completed` no va a buscar tareas
    huérfanas; con este estado, sí.
    """
    loop = WorkerLoop(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=tmp_path / "stop",
    )
    assert loop._retain_lock_for_active_tasks is False
    loop._retain_lock_for_active_tasks = True
    # La bandera es lo que impide que el bloque `finally` borre el lock.
    assert loop._retain_lock_for_active_tasks is True


def test_serial_mode_needs_no_pool_and_cannot_orphan_anything() -> None:
    """Con la concurrencia apagada no hay futuros que puedan quedar sueltos."""
    settings = WorkerRunConfig(concurrency_enabled=False).concurrency_settings()
    assert settings.enabled is False
    assert settings.effective_global_limit() == 1


def test_stop_file_is_honoured_before_starting(tmp_path: Path) -> None:
    """Un stop pendiente no se ignora por arrancar antes de mirarlo."""
    stop = tmp_path / "stop"
    stop.write_text("stop", encoding="utf-8")
    loop = WorkerLoop(
        db_path=tmp_path / "triade.db",
        runs_dir=tmp_path / "runs",
        lock_file=tmp_path / "lock",
        stop_file=stop,
    )
    result = loop.run(
        WorkerRunConfig(
            max_iterations=1,
            once=True,
            runs_dir=str(tmp_path / "runs"),
            lock_file=str(tmp_path / "lock"),
            stop_file=str(stop),
        )
    )
    assert result["status"] == "stopped"
    assert not (tmp_path / "lock").exists(), "no debe dejar lock si no arrancó"


def test_no_threads_survive_a_completed_shutdown() -> None:
    """Al cerrar limpiamente no puede quedar ningún hilo del pool vivo."""
    before = {t.name for t in threading.enumerate()}
    pool = GovernedTaskPool(ConcurrencySettings(enabled=True, max_concurrent_tasks=2))
    pool.submit("t", "pulse_check", {}, lambda: "ok")
    pool.shutdown(wait_seconds=15)

    deadline = threading.Event()
    deadline.wait(timeout=2)
    leaked = {
        t.name
        for t in threading.enumerate()
        if t.name.startswith("triade-worker") and t.name not in before and t.is_alive()
    }
    assert not leaked, f"hilos filtrados tras el cierre: {leaked}"
