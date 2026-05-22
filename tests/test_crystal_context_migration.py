"""Tests de columnas de contexto y migración defensiva del Cristal 1.8F."""

from __future__ import annotations

import sqlite3

from triade.core.bodega import Bodega


CONTEXT_COLUMNS = {
    "context_scope",
    "context_key",
    "comparison_basis",
    "source",
    "intent",
    "session_id",
    "project_id",
    "active_neuron",
}


def test_new_db_has_crystal_context_columns(tmp_path) -> None:
    bodega = Bodega(db_path=tmp_path / "triade.db")
    with bodega._connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(crystal_states)").fetchall()}
    assert CONTEXT_COLUMNS.issubset(columns)


def test_legacy_db_receives_crystal_context_columns(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE crystal_states (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, decision_notes TEXT)"
        )
    bodega = Bodega(db_path=db_path)
    with bodega._connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(crystal_states)").fetchall()}
        indexes = {row["name"] for row in conn.execute("PRAGMA index_list(crystal_states)").fetchall()}
    assert CONTEXT_COLUMNS.issubset(columns)
    assert "idx_crystal_states_context_key" in indexes
