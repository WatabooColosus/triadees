"""La ruta que ejecuta las migraciones de retirada, y sus frenos.

`034`, `035` y `036` llevaban escritas, documentadas y probadas sin ejecutarse
nunca contra ninguna base: Tríade no tiene aplicador central de migraciones —cada
módulo corre la suya cuando la necesita— y una retirada no la necesita nadie.
Diez de las treinta y una deudas reales del 2026-08-10 eran exactamente eso.

Los nombres de tabla salen de las propias migraciones y nunca se escriben
literalmente aquí. Por dos razones: el test no puede desincronizarse de lo que
la migración retira, y un nombre de tabla retirada escrito en un test lo lee el
detector de alias como «lector apuntando al gemelo muerto» —al escribir este
fichero con los nombres a mano, la deuda real subió de 31 a 32—.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.apply_schema_retirements import (
    _tables_dropped_by,
    apply,
    plan,
    requires_anchor_rebase,
    retirement_migrations,
    rollback,
)

#: Las migraciones se descubren igual que en producción, no se nombran: escribir
#: `035_retire_neuron_certifications.sql` mete el nombre de una tabla retirada en
#: el repositorio, que es justo lo que vigila
#: `test_el_contrato_retirado_no_tiene_lector_en_produccion`.
_LIBRES = [m for m in retirement_migrations() if not requires_anchor_rebase(m)]
_CON_ANCLA = [m for m in retirement_migrations() if requires_anchor_rebase(m)]

#: Cada migración declara en su propia cabecera si exige rebasar el ancla de
#: identidad. La lista escrita a mano que había antes sólo marcaba una de las
#: dos que lo piden: leerlo del fichero es la única forma de que no se
#: desincronice.
SIN_ANCLA = [t for m in _LIBRES for t in _tables_dropped_by(m)]
CON_ANCLA = [t for m in _CON_ANCLA for t in _tables_dropped_by(m)]

assert SIN_ANCLA and CON_ANCLA, "el descubrimiento debe encontrar de ambos tipos"


def _base(tmp_path: Path, tablas: dict[str, int]) -> Path:
    db = tmp_path / "triade.db"
    conn = sqlite3.connect(db)
    with conn:
        for tabla, filas in tablas.items():
            conn.execute(f"CREATE TABLE {tabla} (id INTEGER PRIMARY KEY, v TEXT)")
            for i in range(filas):
                conn.execute(f"INSERT INTO {tabla}(v) VALUES('{i}')")
    conn.close()
    return db


def _presentes(db: Path) -> set[str]:
    conn = sqlite3.connect(db)
    try:
        return {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


def _filas(db: Path, tabla: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM '{tabla}'").fetchone()[0])
    finally:
        conn.close()


def test_dry_run_is_the_default_and_touches_nothing(tmp_path: Path) -> None:
    primera = SIN_ANCLA[0]
    db = _base(tmp_path, {primera: 0})

    previsto = plan(db, include_anchor_rebase=False)

    assert primera in previsto["would_drop"]
    assert primera in _presentes(db), "el plan no puede borrar nada"


def test_a_table_with_rows_is_refused_not_dropped(tmp_path: Path) -> None:
    """Una tabla con datos contradice la premisa de la migración: es un hallazgo."""
    con_datos, vacia = SIN_ANCLA[0], CON_ANCLA[0]
    db = _base(tmp_path, {con_datos: 3, vacia: 0})

    resultado = apply(db, include_anchor_rebase=True)

    assert {"table": con_datos, "rows": 3} in resultado["refused_with_rows"]
    assert con_datos not in resultado["dropped"]
    assert vacia in resultado["dropped"]
    assert _filas(db, con_datos) == 3


def test_the_anchor_bound_migration_needs_an_explicit_decision(tmp_path: Path) -> None:
    """Retirarla exige rebasar el ancla de identidad: no lo decide este script."""
    tabla = CON_ANCLA[0]
    db = _base(tmp_path, {tabla: 0})

    bloqueado = plan(db, include_anchor_rebase=False)
    assert tabla not in bloqueado["would_drop"]
    assert any(
        m["blocked"] and m["requires_anchor_rebase"] for m in bloqueado["migrations"]
    )

    permitido = plan(db, include_anchor_rebase=True)
    assert tabla in permitido["would_drop"]


def test_applying_leaves_a_backup_and_an_auditable_manifest(tmp_path: Path) -> None:
    tabla, otra = SIN_ANCLA[0], CON_ANCLA[0]
    db = _base(tmp_path, {tabla: 0, otra: 0})

    resultado = apply(db, include_anchor_rebase=False)

    assert resultado["applied"] is True
    assert otra not in resultado["dropped"], "la de ancla no entra sin la decisión"
    assert Path(resultado["backup"]).exists()
    assert Path(resultado["manifest"]).exists()
    assert set(resultado["dropped"]) >= {tabla}

    esquemas = {
        t["table"]: t["schema"]
        for m in resultado["migrations"]
        for t in m.get("tables", [])
    }
    assert esquemas[tabla] and "CREATE TABLE" in esquemas[tabla]
    assert tabla not in _presentes(db)


def test_rollback_recreates_exactly_what_that_manifest_dropped(tmp_path: Path) -> None:
    """Una operación destructiva sin vuelta atrás no debería ofrecerse."""
    tabla = SIN_ANCLA[0]
    db = _base(tmp_path, {tabla: 0})
    aplicado = apply(db, include_anchor_rebase=False)
    assert tabla not in _presentes(db)

    deshecho = rollback(Path(aplicado["manifest"]), db)

    assert tabla in deshecho["restored"]
    assert tabla in _presentes(db)


def test_rollback_leaves_alone_what_came_back_on_its_own(tmp_path: Path) -> None:
    """Recrear encima de una tabla que volvió sería peor que no hacer nada."""
    tabla = SIN_ANCLA[0]
    db = _base(tmp_path, {tabla: 0})
    aplicado = apply(db, include_anchor_rebase=False)

    conn = sqlite3.connect(db)
    with conn:
        conn.execute(f"CREATE TABLE {tabla} (id INTEGER PRIMARY KEY, otra TEXT)")
    conn.close()

    deshecho = rollback(Path(aplicado["manifest"]), db)

    assert tabla not in deshecho["restored"]
    assert {"table": tabla, "reason": "already_present"} in deshecho["skipped"]


def test_nothing_to_drop_is_not_an_error(tmp_path: Path) -> None:
    db = _base(tmp_path, {"runs": 1})

    resultado = apply(db, include_anchor_rebase=False)

    assert resultado["applied"] is False
    assert resultado["reason"] == "nothing_to_drop"
