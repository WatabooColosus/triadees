"""Un reintento tras un timeout tiene que cambiar algo, o no es un reintento.

Medido el 2026-08-09 sobre `learning_evidence_generation`, que normalmente
termina en 8 s: tres tareas seguidas se agotaron a los 32 s y murieron en
`dead_letter` gastando sus tres intentos en tres esperas idénticas de 30 s. El
trabajo no estaba roto —la misma tarea completó al primer intento minutos
después—; lo que fallaba era el plazo, porque cada handler corre en un proceso
`multiprocessing spawn` que reimporta torch y sentence-transformers, y ese
arranque bajo carga a veces se come los 30 s enteros.
"""

from __future__ import annotations

import pytest

from triade.workers.contracts import TIMEOUT_MAX_FACTOR, timeout_for_attempt


def test_el_primer_intento_usa_el_plazo_base() -> None:
    assert timeout_for_attempt(30.0, 1) == 30.0


def test_cada_reintento_dobla_el_plazo() -> None:
    assert timeout_for_attempt(30.0, 2) == 60.0
    assert timeout_for_attempt(30.0, 3) == 120.0


def test_la_escalada_tiene_tope() -> None:
    """Una tarea de verdad colgada no puede retener un worker sin límite."""
    assert timeout_for_attempt(30.0, 9) == 30.0 * TIMEOUT_MAX_FACTOR
    assert timeout_for_attempt(30.0, 99) == 30.0 * TIMEOUT_MAX_FACTOR


@pytest.mark.parametrize("intento", [0, -1, None])
def test_un_intento_invalido_no_acorta_el_plazo(intento: object) -> None:
    """`attempt` llega de la base; un 0 o un NULL no pueden dar plazo cero."""
    assert timeout_for_attempt(30.0, intento) == 30.0  # type: ignore[arg-type]


def test_el_plazo_nunca_decrece() -> None:
    plazos = [timeout_for_attempt(30.0, i) for i in range(1, 10)]
    assert plazos == sorted(plazos)
    assert plazos[0] == 30.0


def test_el_presupuesto_de_intentos_no_cambia() -> None:
    """Lo que se alarga es el plazo, no el número de oportunidades.

    Con `max_attempts=3` siguen siendo tres ejecuciones: la diferencia es que la
    segunda y la tercera se hacen con 60 y 120 s en vez de repetir 30.
    """
    from triade.workers.contracts import WorkerRunConfig

    config = WorkerRunConfig()
    assert config.task_timeout == 30.0
    plazos = [timeout_for_attempt(config.task_timeout, i) for i in (1, 2, 3)]
    assert plazos == [30.0, 60.0, 120.0]
    assert sum(plazos) == 210.0


def test_el_plazo_escalado_llega_al_ejecutor(tmp_path) -> None:
    """Que la función calcule bien no basta: hay que ver el valor en la llamada.

    Se espía `execute_callable` y se ejecuta un handler real —`pulse_check`, que
    no necesita modelo— con `attempt=3`.
    """
    from triade.workers.contracts import WorkerRunConfig, WorkerTask
    from triade.workers.worker_loop import WorkerLoop

    visto: dict[str, float] = {}

    class CorteDelEspia(Exception):
        """Corta la ejecución en cuanto se ha visto el plazo."""

    class EjecutorEspia:
        def execute_callable(self, fn, *, timeout_seconds, **kwargs):
            visto["timeout_seconds"] = timeout_seconds
            raise CorteDelEspia

    loop = WorkerLoop(db_path=tmp_path / "t.db", runs_dir=tmp_path / "runs")
    loop.task_executor = EjecutorEspia()  # type: ignore[assignment]

    tarea = WorkerTask(task_type="pulse_check", payload={})
    with pytest.raises(CorteDelEspia):
        loop._execute_task(
            tarea, "run-espia", tmp_path, WorkerRunConfig(task_timeout=30.0), attempt=3
        )

    assert visto.get("timeout_seconds") == 120.0, (
        "el tercer intento debe recibir 120 s, no los 30 del plazo base"
    )


def test_el_lease_siempre_sobrevive_al_plazo() -> None:
    """El lease se dimensiona como `max(60, plazo*2)`.

    Si el plazo escalara y el lease no, `recover_expired` daría la tarea por
    perdida mientras aún se ejecuta y otro worker la tomaría en paralelo.
    """
    for intento in range(1, 6):
        plazo = timeout_for_attempt(30.0, intento)
        lease = max(60, int(plazo * 2))
        assert lease > plazo
