"""La educación compite por el hueco, no espera a una ventana vacía.

`TaskLeases.claim()` ordena por `priority − MIN(100, edad_en_minutos)`, así que
quien se encola antes envejece antes y gana. Con `neuron_education_cycle` en 42
y `research_curriculum` en 45, la investigación se encolaba primero en cada
ciclo y salía siempre por delante.

Medido sobre el runtime autónomo el 2026-08-09, en 72 minutos:
`research_curriculum` se ejecutó dos veces —dejando 4 candidatos— y
`neuron_education_cycle` **ninguna**. El sistema investigaba y no estudiaba
nunca lo investigado.
"""

from __future__ import annotations

from triade.workers.mission_planner import MissionPlanner


def _prioridad(planner_source: str, tasks: list) -> int | None:
    for t in tasks:
        if t.source == planner_source:
            return t.priority
    return None


def test_la_educacion_no_va_por_detras_de_la_investigacion(tmp_path) -> None:
    """Lo que hacía que nunca le tocara: peor prioridad y peor edad a la vez."""
    import sqlite3

    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE neurons (id INTEGER PRIMARY KEY, status TEXT, domain TEXT)"
        )
        conn.execute("INSERT INTO neurons (status, domain) VALUES ('experimental','x')")

    planner = MissionPlanner(db_path=db)
    educacion = planner._plan_neuron_education()
    investigacion = planner._plan_research_curriculum()

    assert educacion, "el planner debe encolar educación si hay experimentales"
    assert investigacion
    assert educacion[0].priority < investigacion[0].priority, (
        "la educación tiene que poder ganar el hueco alguna vez"
    )


def test_la_educacion_no_desplaza_a_la_observacion_barata(tmp_path) -> None:
    """Subirla no es ponerla la primera: el pulso y la bodega siguen delante."""
    import sqlite3

    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE neurons (id INTEGER PRIMARY KEY, status TEXT, domain TEXT)"
        )
        conn.execute("INSERT INTO neurons (status, domain) VALUES ('experimental','x')")

    educacion = MissionPlanner(db_path=db)._plan_neuron_education()

    # `bodega_global_review` va en 12 y `semantic_memory_governance` en 13.
    assert educacion[0].priority > 13
