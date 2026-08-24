"""La promoción de neuronas la hace un subsistema cada vez, y se puede probar.

`NeuronAutopromoter.promote()` lista candidatos y los asciende. Lo llamaban tres
sitios que corren como hilos del mismo proceso —`core/runner.py`,
`workers/worker_loop.py` y `core/life_pulse.py`— y sólo el último se protegía,
con un `if not worker_active` que se lee un instante antes de promover y que ni
siquiera contempla al runner. Dos a la vez ascienden el mismo candidato dos
veces.

`orchestrator_locks` existía desde el principio para esto y no lo usaba nadie:
la tabla tenía dos escritores declarados, cero filas, y lo único que se llamaba
era `cleanup()` al arrancar, o sea que se limpiaba lo que nadie creaba.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from triade.core.orchestrator_coord import OrchestratorCoordinator
from triade.db import sqlite3

#: Los tres sitios que llaman a `promote()`. Si alguien añade un cuarto sin
#: lock, o quita el de uno de estos, la prueba de abajo lo dice por su nombre.
CALL_SITES = (
    "triade/core/runner.py",
    "triade/workers/worker_loop.py",
    "triade/core/life_pulse.py",
)


def _rows(db_path: Path) -> list[tuple[str, str]]:
    with sqlite3.connect(str(db_path)) as conn:
        return [
            (str(r[0]), str(r[1]))
            for r in conn.execute("SELECT lock_key, owner FROM orchestrator_locks")
        ]


def test_guard_escribe_la_fila_mientras_dura_y_la_suelta_al_salir(tmp_path):
    coord = OrchestratorCoordinator(db_path=tmp_path / "coord.db")

    with coord.guard(coord.LOCK_NEURON_PROMOTION, "runner", ttl=60.0) as es_mi_turno:
        assert es_mi_turno
        dentro = _rows(tmp_path / "coord.db")

    assert [k for k, _ in dentro] == [coord.LOCK_NEURON_PROMOTION]
    assert dentro[0][1].startswith("runner:")
    assert _rows(tmp_path / "coord.db") == []


def test_guard_suelta_el_lock_aunque_el_cuerpo_reviente(tmp_path):
    """Si no soltara, el subsistema dejaría de promover hasta que expire el TTL.

    Ese fallo se vería como «a veces no promueve» tres minutos después, sin
    nada que apunte al error que lo causó.
    """
    coord = OrchestratorCoordinator(db_path=tmp_path / "coord.db")

    with (
        pytest.raises(RuntimeError),
        coord.guard(coord.LOCK_NEURON_PROMOTION, "workers", ttl=180.0) as es_mi_turno,
    ):
        assert es_mi_turno
        raise RuntimeError("promote() falló a mitad")

    assert _rows(tmp_path / "coord.db") == []


def test_el_segundo_subsistema_no_entra_mientras_el_primero_tiene_el_turno(tmp_path):
    coord = OrchestratorCoordinator(db_path=tmp_path / "coord.db")

    with coord.guard(coord.LOCK_NEURON_PROMOTION, "runner", ttl=60.0) as primero:
        assert primero
        with coord.guard(
            coord.LOCK_NEURON_PROMOTION, "life_pulse", ttl=60.0
        ) as segundo:
            assert segundo is False

    # Y en cuanto el primero suelta, el siguiente sí entra.
    with coord.guard(coord.LOCK_NEURON_PROMOTION, "life_pulse", ttl=60.0) as despues:
        assert despues


def test_dos_hilos_no_promueven_a_la_vez(tmp_path):
    """La carrera real: dos subsistemas entrando al mismo tiempo."""
    coord = OrchestratorCoordinator(db_path=tmp_path / "coord.db")
    dentro_a_la_vez = 0
    maximo_simultaneo = 0
    turnos_concedidos = 0
    mutex = threading.Lock()
    salida = threading.Event()

    def promotor(nombre: str) -> None:
        nonlocal dentro_a_la_vez, maximo_simultaneo, turnos_concedidos
        with coord.guard(coord.LOCK_NEURON_PROMOTION, nombre, ttl=60.0) as es_mi_turno:
            if not es_mi_turno:
                return
            with mutex:
                turnos_concedidos += 1
                dentro_a_la_vez += 1
                maximo_simultaneo = max(maximo_simultaneo, dentro_a_la_vez)
            # Mantener la sección crítica abierta hasta que todos lo intenten:
            # sin esto la prueba pasaría por lo rápido que van, no por el lock.
            salida.wait(timeout=2.0)
            with mutex:
                dentro_a_la_vez -= 1

    hilos = [
        threading.Thread(target=promotor, args=(n,))
        for n in ("runner", "workers", "life_pulse")
    ]
    for h in hilos:
        h.start()
    threading.Event().wait(0.3)
    salida.set()
    for h in hilos:
        h.join(timeout=5.0)

    assert maximo_simultaneo == 1
    assert turnos_concedidos == 1


def test_los_tres_llamantes_de_promote_pasan_por_el_lock():
    """Estructural: que nadie vuelva a promover por fuera del turno."""
    raiz = Path(__file__).resolve().parents[1]
    for relativo in CALL_SITES:
        texto = (raiz / relativo).read_text(encoding="utf-8")
        assert ".promote()" in texto, f"{relativo} ya no promueve; revisa esta lista"
        assert "LOCK_NEURON_PROMOTION" in texto, (
            f"{relativo} llama a promote() sin pasar por el lock de coordinación"
        )
