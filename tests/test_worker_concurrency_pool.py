"""El pool ejecuta de verdad en paralelo lo que la política permite.

`test_worker_concurrency_policy.py` prueba la *decisión*. Aquí se prueba la
*ejecución*: hilos reales, solapamiento observable y liberación de exclusiones.
El solapamiento no se mide con `sleep` y cronómetro —eso sería una prueba
temporal frágil— sino con una barrera: si dos tareas no corrieran a la vez, la
barrera expiraría y el test fallaría de forma determinista.
"""

from __future__ import annotations

import threading
import time

import pytest

from triade.workers.concurrency import (
    ConcurrencySettings,
    GovernedTaskPool,
    RunningTaskRegistry,
)


def _pool(**kwargs: object) -> GovernedTaskPool:
    settings = ConcurrencySettings(enabled=True, **kwargs)  # type: ignore[arg-type]
    return GovernedTaskPool(settings)


def test_two_read_only_tasks_overlap_in_real_threads() -> None:
    """La prueba central del objetivo B: dos tareas seguras a la vez."""
    pool = _pool(max_concurrent_tasks=4, read_only_workers=4)
    barrier = threading.Barrier(2, timeout=10)
    threads: list[str] = []

    def work() -> str:
        name = threading.current_thread().name
        threads.append(name)
        barrier.wait()  # solo pasa si LAS DOS estan dentro a la vez
        return name

    try:
        assert pool.submit("t1", "pulse_check", {}, work).admitted
        assert pool.submit("t2", "system_debt_scan", {}, work).admitted
        deadline = time.monotonic() + 15
        while pool.pending_count() and time.monotonic() < deadline:
            pool.wait_for_slot(0.2)
            pool.collect_finished()
        assert len(threads) == 2
        assert threads[0] != threads[1], "corrieron en el mismo hilo, no en paralelo"
    finally:
        pool.shutdown(wait_seconds=5)


def test_critical_mutation_never_overlaps() -> None:
    """Si esto falla, dos promociones podrian mutar lo estable a la vez."""
    pool = _pool(max_concurrent_tasks=4, critical_mutation_workers=1)
    inside = threading.Event()
    release = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=10)
        return "done"

    try:
        assert pool.submit(
            "c1", "neuron_autopromotion", {"neuron_id": "n-1"}, blocking
        ).admitted
        assert inside.wait(timeout=10)
        denied = pool.submit(
            "c2", "neuron_autopromotion", {"neuron_id": "n-2"}, lambda: "no"
        )
        assert not denied.admitted
    finally:
        release.set()
        pool.shutdown(wait_seconds=5)


def test_same_candidate_is_refused_while_the_first_is_running() -> None:
    pool = _pool(max_concurrent_tasks=4, evaluation_workers=2)
    inside = threading.Event()
    release = threading.Event()
    payload = {"candidate_id": "cand-1", "neuron_id": "n-1"}

    def blocking() -> str:
        inside.set()
        release.wait(timeout=10)
        return "done"

    try:
        assert pool.submit(
            "e1", "self_improvement_evaluation", payload, blocking
        ).admitted
        assert inside.wait(timeout=10)
        denied = pool.submit(
            "e2", "self_improvement_evaluation", dict(payload), lambda: "no"
        )
        assert not denied.admitted
        assert denied.reason.startswith("exclusive_key_held:")
        # Otra candidata distinta si entra: el carril no esta cerrado, solo la clave.
        other = pool.submit(
            "e3",
            "self_improvement_evaluation",
            {"candidate_id": "cand-2", "neuron_id": "n-2"},
            lambda: "ok",
        )
        assert other.admitted
    finally:
        release.set()
        pool.shutdown(wait_seconds=5)


def test_exclusive_key_is_released_even_if_the_task_raises() -> None:
    """Una tarea que revienta no puede dejar la candidata bloqueada para siempre."""
    pool = _pool(max_concurrent_tasks=4, evaluation_workers=2)
    payload = {"candidate_id": "cand-7"}

    def boom() -> str:
        raise RuntimeError("fallo simulado del sandbox")

    try:
        assert pool.submit("e1", "self_improvement_evaluation", payload, boom).admitted
        deadline = time.monotonic() + 10
        while pool.pending_count() and time.monotonic() < deadline:
            pool.wait_for_slot(0.2)
            pool.collect_finished()
        assert not pool.registry.holds_key("candidate_id=cand-7")
        assert pool.submit(
            "e2", "self_improvement_evaluation", dict(payload), lambda: "ok"
        ).admitted
    finally:
        pool.shutdown(wait_seconds=5)


def test_collect_finished_surfaces_the_exception() -> None:
    """El fallo debe llegar a quien cierra la tarea, no perderse en el hilo."""
    pool = _pool(max_concurrent_tasks=2)

    def boom() -> str:
        raise RuntimeError("fallo simulado")

    try:
        pool.submit("t1", "pulse_check", {}, boom)
        deadline = time.monotonic() + 10
        finished: list[tuple[str, object]] = []
        while not finished and time.monotonic() < deadline:
            pool.wait_for_slot(0.2)
            finished = list(pool.collect_finished())
        assert len(finished) == 1
        task_id, future = finished[0]
        assert task_id == "t1"
        with pytest.raises(RuntimeError, match="fallo simulado"):
            future.result()  # type: ignore[attr-defined]
    finally:
        pool.shutdown(wait_seconds=5)


def test_collect_finished_removes_the_future_only_once() -> None:
    pool = _pool(max_concurrent_tasks=2)
    try:
        pool.submit("t1", "pulse_check", {}, lambda: "ok")
        deadline = time.monotonic() + 10
        collected: list[tuple[str, object]] = []
        while not collected and time.monotonic() < deadline:
            pool.wait_for_slot(0.2)
            collected = list(pool.collect_finished())
        assert len(collected) == 1
        assert pool.collect_finished() == []
        assert pool.pending_count() == 0
    finally:
        pool.shutdown(wait_seconds=5)


def test_stop_accepting_refuses_new_work_without_touching_the_running_one() -> None:
    """Al parar: no se aceptan tareas nuevas, la viva sigue siendo suya."""
    pool = _pool(max_concurrent_tasks=4)
    inside = threading.Event()
    release = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=10)
        return "done"

    try:
        assert pool.submit("t1", "pulse_check", {}, blocking).admitted
        assert inside.wait(timeout=10)
        pool.stop_accepting()
        denied = pool.submit("t2", "pulse_check", {}, lambda: "no")
        assert not denied.admitted
        assert denied.reason == "pool_closed"
        assert pool.registry.running_count() == 1
    finally:
        release.set()
        pool.shutdown(wait_seconds=5)


def test_shutdown_reports_tasks_that_were_still_running() -> None:
    """No se declara terminada una tarea que sigue viva: se reporta y punto.

    Su lease sigue siendo suyo; la recuperacion por expiracion de lease es el
    mecanismo que ya existe para esto, y no se duplica aqui.
    """
    pool = _pool(max_concurrent_tasks=4)
    inside = threading.Event()
    release = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=30)
        return "done"

    pool.submit("t1", "pulse_check", {}, blocking)
    assert inside.wait(timeout=10)
    report = pool.shutdown(wait_seconds=0.5)
    assert report["still_running"] == 1
    assert not pool.accepting
    release.set()


def test_shutdown_waits_for_a_task_that_finishes_in_time() -> None:
    pool = _pool(max_concurrent_tasks=4)
    done = threading.Event()

    def quick() -> str:
        time.sleep(0.2)
        done.set()
        return "done"

    pool.submit("t1", "pulse_check", {}, quick)
    report = pool.shutdown(wait_seconds=10)
    assert done.is_set()
    assert report["still_running"] == 0


def test_disabled_concurrency_runs_one_task_at_a_time() -> None:
    """Modo serial: equivalente al comportamiento anterior."""
    pool = GovernedTaskPool(ConcurrencySettings.serial())
    inside = threading.Event()
    release = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=10)
        return "done"

    try:
        assert pool.submit("t1", "pulse_check", {}, blocking).admitted
        assert inside.wait(timeout=10)
        denied = pool.submit("t2", "pulse_check", {}, lambda: "no")
        assert not denied.admitted
        assert denied.reason == "global_limit"
    finally:
        release.set()
        pool.shutdown(wait_seconds=5)


def test_registry_admission_is_race_free_under_real_contention() -> None:
    """Muchos hilos peleando por la misma clave: solo uno puede ganar.

    Es la garantia que sostiene "dos tareas nunca mutan la misma candidata".
    Sin el lock compartido entre comprobar y tomar, este test es flaky por
    diseno; con el, es determinista.
    """
    registry = RunningTaskRegistry(
        ConcurrencySettings(
            enabled=True, max_concurrent_tasks=32, evaluation_workers=32
        )
    )
    payload = {"candidate_id": "cand-unica"}
    admitted: list[str] = []
    lock = threading.Lock()
    start = threading.Barrier(16, timeout=15)

    def contend(index: int) -> None:
        start.wait()
        decision = registry.try_admit(
            f"t{index}", "self_improvement_evaluation", payload
        )
        if decision.admitted:
            with lock:
                admitted.append(f"t{index}")

    threads = [threading.Thread(target=contend, args=(i,)) for i in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert len(admitted) == 1, f"mas de un ganador: {admitted}"


def test_snapshot_reflects_live_execution() -> None:
    pool = _pool(max_concurrent_tasks=4, read_only_workers=4)
    inside = threading.Event()
    release = threading.Event()

    def blocking() -> str:
        inside.set()
        release.wait(timeout=10)
        return "done"

    try:
        pool.submit("t1", "pulse_check", {}, blocking)
        assert inside.wait(timeout=10)
        snapshot = pool.snapshot(queued=3)
        assert snapshot["running"] == 1
        assert snapshot["queued"] == 3
        assert snapshot["lanes"]["read_only"]["running"] == 1
        (entry,) = pool.registry.running_tasks()
        assert entry.thread_name, "el hilo ejecutor debe quedar registrado"
    finally:
        release.set()
        pool.shutdown(wait_seconds=5)
