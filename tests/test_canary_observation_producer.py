"""Un canary que arranca tiene que observarse solo.

Auditoría 2026-08-02, P1-02. `self_improvement_canary_observation` estaba
declarado en `WORKER_TASK_TYPES`, tenía política de concurrencia y un handler
completo (`worker_loop.py:1861`) — y **cero productores en todo el repositorio**,
verificado por AST, no por búsqueda textual. Cero ejecuciones en toda la
historia de `autonomous_tasks`.

`_self_improvement_evaluation` termina como mucho en `canary_running` y no
agenda nada después. `_plan_self_improvement()` solo encolaba la evaluación. El
resultado: un canary se abre y no se observa nunca. Ni gradúa, ni se revierte,
ni acumula observaciones. Es el patrón «ciclo que crea evidencia sin proceso de
resolución posterior».

El productor va en el planificador, no dentro de la evaluación, por lo que dice
el propio handler: esperar dentro de `run_once()` a que ocurran suficientes
conversaciones significaría sostener un lease durante horas. Cada ciclo aporta
lo que haya y se va.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.workers.mission_planner import MissionPlanner


def _db(tmp_path: Path, *, con_canary: bool, status: str = "running") -> Path:
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.execute(
            """CREATE TABLE improvement_canaries (
                canary_id TEXT PRIMARY KEY, candidate_id TEXT, status TEXT,
                created_at TEXT)"""
        )
        if con_canary:
            conn.execute(
                "INSERT INTO improvement_canaries VALUES "
                "('can-1','cand-1',?,'2026-08-02T00:00:00+00:00')",
                (status,),
            )
        conn.commit()
    return ruta


def _tipos(tareas) -> list[str]:
    return [t.task_type for t in tareas]


class TestElCanaryAbiertoSeAgenda:
    def test_con_canary_corriendo_se_planifica_la_observacion(
        self, tmp_path: Path
    ) -> None:
        planner = MissionPlanner(_db(tmp_path, con_canary=True))

        tareas = planner._plan_canary_observation()

        assert "self_improvement_canary_observation" in _tipos(tareas), (
            "hay un canary abierto y nadie agenda su observación: no graduará "
            "ni se revertirá nunca"
        )

    def test_la_tarea_lleva_el_candidato(self, tmp_path: Path) -> None:
        """Sin `candidate_id` la clave de exclusión no protege nada."""
        planner = MissionPlanner(_db(tmp_path, con_canary=True))

        tarea = planner._plan_canary_observation()[0]

        assert tarea.payload.get("candidate_id") == "cand-1"
        assert tarea.reason


class TestNoGiraEnVacio:
    def test_sin_canary_no_agenda_nada(self, tmp_path: Path) -> None:
        planner = MissionPlanner(_db(tmp_path, con_canary=False))
        assert planner._plan_canary_observation() == []

    def test_canary_ya_cerrado_no_se_observa(self, tmp_path: Path) -> None:
        planner = MissionPlanner(_db(tmp_path, con_canary=True, status="graduated"))
        assert planner._plan_canary_observation() == []

    def test_sin_la_tabla_no_revienta(self, tmp_path: Path) -> None:
        """La tabla no existe todavía en producción."""
        ruta = tmp_path / "vacia.db"
        sqlite3.connect(ruta).close()
        assert MissionPlanner(ruta)._plan_canary_observation() == []


class TestEntraEnElCicloDePlanificacion:
    def test_plan_cycle_incluye_la_observacion(self, tmp_path: Path) -> None:
        """Un planificador que no lo llama deja el productor desconectado."""
        planner = MissionPlanner(_db(tmp_path, con_canary=True))

        tareas = planner.plan_cycle()

        assert "self_improvement_canary_observation" in _tipos(tareas)
