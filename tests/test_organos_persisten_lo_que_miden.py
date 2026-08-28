"""Un órgano conectado deja evidencia; una isla legacy se retira completa."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.constitution.enforcer import ConstitutionEnforcer


def _tablas(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    nombres = {
        str(r[0])
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    return nombres


def test_el_enforcer_no_escribe_en_memoria_volatil() -> None:
    from triade.constitution.enforcer import DEFAULT_DB_PATH

    assert DEFAULT_DB_PATH != ":memory:"
    assert DEFAULT_DB_PATH.endswith(".db")


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
    importador y ninguno es un test: invisibles los dos. Este detector permitió
    encontrar y retirar la isla T-007..T-024, gemela del runtime vivo.

    Lo que separa «alguien lo importa» de «el sistema lo conecta» es la
    alcanzabilidad desde un entrypoint que algo arranca. La función ya existía
    y el informe no la usaba.
    """
    from triade.observability.introspection import build_debt_report

    reporte = build_debt_report(Path("."), db_path=None)
    entrada = reporte["items"].get("modules_unreachable_from_entrypoint")
    assert entrada is not None, "la categoría tiene que existir siempre"
    assert "import_graph.json" in entrada["evidence"]
    # Los `__init__.py` no cuentan: Python los ejecuta al importar cualquier
    # submódulo, así que un paquete vivo tendría el suyo «inalcanzable».
    assert not any(str(x).endswith("__init__.py") for x in entrada["items"]), entrada[
        "items"
    ]
