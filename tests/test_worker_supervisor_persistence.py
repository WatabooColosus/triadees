"""El supervisor de workers escribe donde alguien pueda leerlo.

`WorkerSupervisor` es el mecanismo antivuelco de Tríade: `stuck_tasks()` detecta
tareas colgadas, `health_snapshot()` registra el estado de cada worker,
`unhealthy_workers()` los recupera y `auto_restart_check()` decide si reiniciar.
Está entero y bien escrito.

Y no ha podido detectar un cuelgue nunca. El constructor caía a `:memory:`
cuando nadie pasaba ruta, y **los tres sitios que lo instancian lo hacen sin
ruta** — `system_monitor.py:378`, `dashboard/routes.py:305`,
`triadeos_complete.py:198`, todos `WorkerSupervisor()`. Creaba sus cinco tablas
en RAM, las usaba y las tiraba al volver de la función.

Medido en producción el 2026-08-09: las cinco tablas —`worker_consumption`,
`worker_time_log`, `worker_ownership`, `worker_restart_log`,
`worker_health_snapshots`— **no existían** en `triade/memory/triade.db`, con
`triadeos_service` corriendo y ejecutando ciclos. No era un fallo del
supervisor: funcionaba sobre una base que dejaba de existir.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.workers.worker_supervisor import WorkerSupervisor

TABLAS = (
    "worker_consumption",
    "worker_time_log",
    "worker_ownership",
    "worker_restart_log",
    "worker_health_snapshots",
)


def _tablas(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def test_el_supervisor_persiste_en_la_base_que_se_le_da(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"

    supervisor = WorkerSupervisor(str(db_path))
    supervisor.health_snapshot("worker-1", status="degraded")
    del supervisor

    # Otra instancia, otra conexión: si viviera en RAM no vería nada.
    assert set(TABLAS) <= _tablas(db_path)
    recuperado = WorkerSupervisor(str(db_path)).get_health("worker-1")
    assert recuperado is not None
    assert recuperado["status"] == "degraded"


def test_lo_registrado_sobrevive_a_la_instancia(tmp_path: Path) -> None:
    """El caso real: quien registra y quien consulta son objetos distintos.

    `triadeos_complete` instancia el supervisor y lo suelta; el panel crea otro
    para preguntar. Con `:memory:` el segundo nunca veía lo del primero.
    """
    db_path = tmp_path / "triade.db"

    WorkerSupervisor(str(db_path)).health_snapshot("worker-2", status="unhealthy")

    enfermos = WorkerSupervisor(str(db_path)).unhealthy_workers()

    assert [w["worker_id"] for w in enfermos] == ["worker-2"]


def test_una_tarea_colgada_se_ve_desde_otra_instancia(tmp_path: Path) -> None:
    """`stuck_tasks()` devolvía `[]` siempre: leía una tabla recién creada."""
    db_path = tmp_path / "triade.db"

    registro = WorkerSupervisor(str(db_path)).start_task(
        "worker-3", "task-colgada", task_type="neuron_education_cycle"
    )
    assert registro

    # timeout 0 ms: cualquier tarea viva cuenta como colgada.
    colgadas = WorkerSupervisor(str(db_path)).stuck_tasks(timeout_ms=0)

    assert [t["task_id"] for t in colgadas] == ["task-colgada"]


def test_memoria_sigue_disponible_si_se_pide_explicitamente() -> None:
    """Una prueba puede querer RAM; lo que no vale es que sea el silencio."""
    supervisor = WorkerSupervisor(":memory:")
    supervisor.health_snapshot("worker-4", status="ok")

    assert supervisor.get_health("worker-4") is not None


def test_el_defecto_ya_no_es_memoria() -> None:
    assert WorkerSupervisor.DEFAULT_DB_PATH == "triade/memory/triade.db"
