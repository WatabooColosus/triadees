"""La ruta que ejecuta las migraciones de retirada, y sus frenos.

`034`, `035` y `036` llevaban escritas, documentadas y probadas sin ejecutarse
nunca contra ninguna base: Tríade no tiene aplicador central de migraciones —cada
módulo corre la suya cuando la necesita— y una retirada no la necesita nadie.
Diez de las treinta y una deudas reales del 2026-08-10 eran exactamente eso.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.apply_schema_retirements import apply, plan


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


def test_dry_run_is_the_default_and_touches_nothing(tmp_path: Path) -> None:
    db = _base(tmp_path, {"benchmark_results": 0, "user_sessions": 0})

    previsto = plan(db, include_anchor_rebase=False)

    assert "benchmark_results" in previsto["would_drop"]
    conn = sqlite3.connect(db)
    presentes = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert "benchmark_results" in presentes, "el plan no puede borrar nada"


def test_a_table_with_rows_is_refused_not_dropped(tmp_path: Path) -> None:
    """Una tabla con datos contradice la premisa de la migración: es un hallazgo."""
    db = _base(tmp_path, {"benchmark_results": 3, "user_sessions": 0})

    resultado = apply(db, include_anchor_rebase=False)

    assert {"table": "benchmark_results", "rows": 3} in resultado["refused_with_rows"]
    assert "benchmark_results" not in resultado["dropped"]
    assert "user_sessions" in resultado["dropped"]

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM benchmark_results").fetchone()[0] == 3
    conn.close()


def test_goals_needs_the_explicit_identity_decision(tmp_path: Path) -> None:
    """Retirar `goals` exige rebasar el ancla: no es decisión de este script."""
    db = _base(tmp_path, {"goals": 0})

    bloqueado = plan(db, include_anchor_rebase=False)
    assert "goals" not in bloqueado["would_drop"]
    assert any(
        m["migration"] == "036_retire_goals.sql" and m["blocked"]
        for m in bloqueado["migrations"]
    )

    permitido = plan(db, include_anchor_rebase=True)
    assert "goals" in permitido["would_drop"]


def test_applying_leaves_a_backup_and_an_auditable_manifest(tmp_path: Path) -> None:
    db = _base(tmp_path, {"user_sessions": 0, "meta_model_decisions": 0})

    resultado = apply(db, include_anchor_rebase=False)

    assert resultado["applied"] is True
    assert Path(resultado["backup"]).exists()
    assert Path(resultado["manifest"]).exists()
    assert set(resultado["dropped"]) >= {"user_sessions", "meta_model_decisions"}

    # El esquema retirado queda escrito: la decisión es reversible a mano.
    esquemas = {
        t["table"]: t["schema"]
        for m in resultado["migrations"]
        for t in m.get("tables", [])
    }
    assert esquemas["user_sessions"] and "CREATE TABLE" in esquemas["user_sessions"]

    conn = sqlite3.connect(db)
    presentes = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    conn.close()
    assert "user_sessions" not in presentes


def test_nothing_to_drop_is_not_an_error(tmp_path: Path) -> None:
    db = _base(tmp_path, {"runs": 1})

    resultado = apply(db, include_anchor_rebase=False)

    assert resultado["applied"] is False
    assert resultado["reason"] == "nothing_to_drop"
