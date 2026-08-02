"""El vocabulario de estados de tarea es uno solo.

No es una prueba de estilo. Las copias que había divergían de verdad, y una
copia divergente no falla al escribirse: falla cuando alguien añade un estado y
sólo se entera una de ellas. `deferred` y `completion_uncertain` se añadieron a
la cola y ninguna de las copias se enteró.

También se fija que los sensores del organismo miran la cola **viva**. Contaban
`worker_tasks`, retirada por trigger en `019_legacy_retirement.sql` y sin una
escritura desde el 2026-07-29: el hipotálamo devolvía 0 workers activos con dos
tareas corriendo y 1.497 ejecutadas en 24 h.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.hypothalamus.senses import SystemSenses
from triade.learning.doctor import ACTIVE_STATUSES
from triade.metabolism.health import HealthSensors
from triade.runtime.task_status import (
    ACTIVE,
    ALL_STATES,
    ELIGIBLE,
    IN_FLIGHT,
    TERMINAL,
    TERMINAL_FAILURE,
    is_active,
    is_terminal,
    sql_placeholders,
)
from triade.workers.contracts import TERMINAL_TASK_STATUSES

ESQUEMA = """
CREATE TABLE autonomous_tasks (
    task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL, status TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


def _db(tmp_path: Path, estados: list[str]) -> Path:
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.executescript(ESQUEMA)
        for i, estado in enumerate(estados):
            conn.execute(
                "INSERT INTO autonomous_tasks VALUES (?,?,?,?,?)",
                (f"t{i}", "pulse_check", estado, "2026-08-02", "2026-08-02"),
            )
        conn.commit()
    return ruta


class TestUnSoloVocabulario:
    def test_activo_y_terminal_no_se_solapan(self) -> None:
        assert ACTIVE & TERMINAL == frozenset()

    def test_elegible_y_en_vuelo_reparten_lo_activo(self) -> None:
        assert ELIGIBLE | IN_FLIGHT == ACTIVE
        assert ELIGIBLE & IN_FLIGHT == frozenset()

    def test_el_doctor_usa_el_mismo_activo(self) -> None:
        # Le faltaban `deferred` y `completion_uncertain`: una tarea diferida
        # era invisible para el doctor y visible para el planificador.
        assert set(ACTIVE_STATUSES) == set(ACTIVE)

    def test_los_terminales_de_workers_son_todos(self) -> None:
        # Era {completed, failed, blocked, skipped}: dejaba fuera `observed` y
        # `dead_letter`, que en producción son el 7 % de la cola.
        assert set(TERMINAL_TASK_STATUSES) == set(TERMINAL)
        assert {"observed", "dead_letter"} <= set(TERMINAL_TASK_STATUSES)

    def test_los_finales_sin_veredicto_cuentan_como_fallo(self) -> None:
        # No saber cómo acabó no es haber acabado bien.
        assert {"timeout", "lease_lost"} <= TERMINAL_FAILURE

    def test_completion_uncertain_sigue_viva(self) -> None:
        # Se ejecutó pero nadie probó el efecto: darla por terminada seria
        # afirmar un resultado que no se verificó.
        assert is_active("completion_uncertain")
        assert not is_terminal("completion_uncertain")

    def test_placeholders_estables_y_completos(self) -> None:
        marcadores, estados = sql_placeholders(ACTIVE)
        assert marcadores == ",".join("?" * len(ACTIVE))
        assert estados == tuple(sorted(ACTIVE))
        # Estable entre llamadas: un IN(...) que se reordena hace ilegibles los
        # diffs de logs y los planes de consulta.
        assert sql_placeholders(ACTIVE) == (marcadores, estados)

    def test_ningun_estado_se_queda_fuera(self) -> None:
        assert ALL_STATES == ACTIVE | TERMINAL


class TestLosSensoresMiranLaColaViva:
    def test_hipotalamo_cuenta_las_tareas_en_vuelo(self, tmp_path: Path) -> None:
        db = _db(tmp_path, ["running", "leased", "completed", "observed"])

        assert SystemSenses(db_path=db).active_workers() == 2

    def test_hipotalamo_cuenta_recovered_como_espera(self, tmp_path: Path) -> None:
        # El sensor viejo sólo miraba 'pending'/'queued'. En producción había
        # una tarea en `recovered` que no veía nadie.
        db = _db(tmp_path, ["pending", "recovered", "deferred", "completed"])

        assert SystemSenses(db_path=db).pending_tasks() == 3

    def test_metabolismo_cuenta_la_cola_elegible(self, tmp_path: Path) -> None:
        db = _db(tmp_path, ["pending", "retry_wait", "running", "completed"])

        assert HealthSensors(db_path=db)._check_queue()["pending"] == 2

    def test_sin_cola_v2_no_revienta(self, tmp_path: Path) -> None:
        vacia = tmp_path / "vacia.db"
        sqlite3.connect(vacia).close()

        assert SystemSenses(db_path=vacia).active_workers() == 0
        assert HealthSensors(db_path=vacia)._check_queue()["pending"] == 0
