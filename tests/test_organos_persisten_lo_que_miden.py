"""Un órgano que mide y no deja rastro no ha medido nada.

Encontrado el 2026-08-27 barriendo qué existe en el repositorio y no está
conectado. `SystemMonitor` (T-019) y `ConstitutionEnforcer` construían su
conexión con `sqlite3.connect(db_path or ":memory:")`, y sus dos llamadores de
producción —`dashboard/routes.py` y `os/triadeos_complete.py`— los instancian
**sin argumentos**. Resultado medido sobre la base viva: `monitor_signals`,
`monitor_snapshots`, `constitution_violations` y `constitution_checks` no
existían siquiera como tablas. El monitor tomaba CPU, RAM, GPU, disco y
temperatura en cada ciclo de TriadeOS y lo escribía en RAM para tirarlo.

El repositorio ya tenía la convención de una ruta real por defecto en 161
sitios. Aquí faltaba, y por eso dos órganos enteros funcionaban sin dejar
huella.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.constitution.enforcer import ConstitutionEnforcer
from triade.core.system_monitor import SystemMonitor


def _tablas(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    nombres = {
        str(r[0])
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    return nombres


def test_el_monitor_no_escribe_en_memoria_volatil() -> None:
    """La ruta por defecto tiene que ser una base real, no `:memory:`."""
    from triade.core.system_monitor import DEFAULT_DB_PATH

    assert DEFAULT_DB_PATH != ":memory:"
    assert DEFAULT_DB_PATH.endswith(".db")


def test_el_enforcer_no_escribe_en_memoria_volatil() -> None:
    from triade.constitution.enforcer import DEFAULT_DB_PATH

    assert DEFAULT_DB_PATH != ":memory:"
    assert DEFAULT_DB_PATH.endswith(".db")


def test_una_medicion_del_monitor_sobrevive_al_objeto(tmp_path: Path) -> None:
    """Es lo que `:memory:` impedía: el dato moría con la instancia."""
    db = tmp_path / "triade.db"
    SystemMonitor(db_path=str(db)).snapshot()

    assert "monitor_snapshots" in _tablas(db)
    conn = sqlite3.connect(db)
    filas = conn.execute("SELECT COUNT(*) FROM monitor_snapshots").fetchone()[0]
    conn.close()
    assert filas == 1

    # Otro objeto, misma base: el dato sigue ahí. Con `:memory:` cada
    # instancia abría su propia base vacía y esto daba 0.
    otro = SystemMonitor(db_path=str(db))
    otro.snapshot()
    conn = sqlite3.connect(db)
    acumuladas = conn.execute("SELECT COUNT(*) FROM monitor_snapshots").fetchone()[0]
    conn.close()
    assert acumuladas == 2


def test_una_comprobacion_constitucional_queda_registrada(tmp_path: Path) -> None:
    """Comprobar la constitución y no anotarlo deja el gate sin auditoría."""
    db = tmp_path / "triade.db"
    resultado = ConstitutionEnforcer(db_path=str(db)).check_article("runner", 1)
    assert resultado["status"] in {"pass", "violation", "warning"}

    assert "constitution_checks" in _tablas(db)
    conn = sqlite3.connect(db)
    filas = conn.execute("SELECT COUNT(*) FROM constitution_checks").fetchone()[0]
    conn.close()
    assert filas >= 1


# ── las islas tienen que verse ────────────────────────────────────────


def test_el_informe_de_deuda_ve_los_modulos_que_nadie_alcanza() -> None:
    """Una isla de módulos que se importan entre sí pasaba los dos filtros.

    `modules_without_importer` y `modules_imported_only_by_tests` miran *quién
    importa*. Si dos módulos huérfanos se importan mutuamente, cada uno tiene
    importador y ninguno es un test: invisibles los dos. Medido el 2026-08-27,
    el informe daba `modules_without_importer: 0` mientras `triade/dashboard/`
    y `triade/os/triadeos_complete.py` —gemelo del TriadeOS que sí corre, 304
    ciclos al día— estaban desconectados del sistema entero, y con ellos los
    únicos consumidores de `SystemMonitor` y `ConstitutionEnforcer`.

    Lo que separa «alguien lo importa» de «el sistema lo conecta» es la
    alcanzabilidad desde un entrypoint que algo arranca. La función ya existía
    y el informe no la usaba.
    """
    from triade.observability.introspection import build_debt_report

    reporte = build_debt_report(Path("."), db_path=None)
    entrada = reporte["items"].get("modules_unreachable_from_entrypoint")
    assert entrada is not None, "la categoría tiene que existir siempre"
    assert "reachable_modules" in entrada["evidence"]
    # Los `__init__.py` no cuentan: Python los ejecuta al importar cualquier
    # submódulo, así que un paquete vivo tendría el suyo «inalcanzable».
    assert not any(str(x).endswith("__init__.py") for x in entrada["items"]), entrada[
        "items"
    ]
