"""Tests de migración y persistencia Crystal DB 1.8B."""

from __future__ import annotations

import sqlite3

from triade.core.bodega import Bodega
from triade.core.contracts import MemoryPacket, SignalPacket
from triade.core.crystal import Crystal


def test_crystal_states_has_v2_columns(tmp_path) -> None:
    db_path = tmp_path / "triade.db"
    bodega = Bodega(db_path=db_path)

    with bodega._connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(crystal_states)").fetchall()}

    assert "pv7_score" in columns
    assert "stability" in columns
    assert "intensity" in columns
    assert "q_crystal" in columns
    assert "ethics_vector" in columns
    assert "regulation_notes" in columns


def test_store_crystal_persists_v2_fields(tmp_path) -> None:
    db_path = tmp_path / "triade.db"
    bodega = Bodega(db_path=db_path)
    signals = SignalPacket(
        run_id="run-crystal-db",
        intent="conversation",
        tone="constructive",
        urgency="medium",
        risk="low",
        pv7={"humildad": 0.8, "generosidad": 0.8, "respeto": 0.9, "paciencia": 0.7, "templanza": 0.8, "caridad": 0.8, "diligencia": 0.9},
    )
    memory = MemoryPacket(run_id="run-crystal-db", confidence=0.8)
    crystal = Crystal().regulate(signals, memory)

    bodega.store_crystal(crystal)

    with bodega._connect() as conn:
        row = conn.execute("SELECT * FROM crystal_states WHERE run_id = ?", ("run-crystal-db",)).fetchone()

    assert row["pv7_score"] == crystal.pv7_score
    assert row["stability"] == crystal.stability
    assert row["intensity"] == crystal.intensity
    assert row["q_crystal"] == crystal.q_crystal
    assert "virtue_alignment" in row["ethics_vector"]
    assert "Cristal v2" in row["regulation_notes"]


def test_migrate_existing_crystal_table(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE crystal_states (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                ethics REAL DEFAULT 0.8,
                depth REAL DEFAULT 0.6,
                creativity REAL DEFAULT 0.5,
                relation REAL DEFAULT 0.7,
                decision_notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    bodega = Bodega(db_path=db_path)
    with bodega._connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(crystal_states)").fetchall()}

    assert "q_crystal" in columns
    assert "ethics_vector" in columns
    assert "regulation_notes" in columns
