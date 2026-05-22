"""Tests de migración y persistencia Crystal DB 1.8D."""

from __future__ import annotations

import sqlite3

from triade.core.bodega import Bodega
from triade.core.contracts import InputPacket, MemoryPacket, SignalPacket
from triade.core.crystal import Crystal


TEMPORAL_COLUMNS = {
    "previous_q_crystal",
    "previous_stability",
    "q_delta",
    "stability_delta",
    "temporal_status",
    "temporal_alerts",
    "history_window",
}


def test_crystal_states_has_v2_and_temporal_columns(tmp_path) -> None:
    db_path = tmp_path / "triade.db"
    bodega = Bodega(db_path=db_path)

    with bodega._connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(crystal_states)").fetchall()}

    assert {"pv7_score", "stability", "intensity", "q_crystal", "ethics_vector", "regulation_notes"}.issubset(columns)
    assert TEMPORAL_COLUMNS.issubset(columns)


def test_store_crystal_persists_v2_and_temporal_fields(tmp_path) -> None:
    db_path = tmp_path / "triade.db"
    bodega = Bodega(db_path=db_path)

    bodega.create_run(InputPacket(user_input="Primera base", source="test", run_id="run-base"))
    base_signals = SignalPacket(
        run_id="run-base",
        intent="conversation",
        tone="constructive",
        urgency="low",
        risk="low",
        pv7={"humildad": 0.8, "generosidad": 0.8, "respeto": 0.9, "paciencia": 0.7, "templanza": 0.8, "caridad": 0.8, "diligencia": 0.9},
    )
    base = Crystal().regulate(base_signals, MemoryPacket(run_id="run-base", confidence=0.8))
    bodega.store_crystal(base)

    run_id = "run-crystal-db"
    bodega.create_run(InputPacket(user_input="Prueba crystal temporal", source="test", run_id=run_id))
    signals = SignalPacket(
        run_id=run_id,
        intent="conversation",
        tone="constructive",
        urgency="medium",
        risk="low",
        pv7={"humildad": 0.8, "generosidad": 0.8, "respeto": 0.9, "paciencia": 0.7, "templanza": 0.8, "caridad": 0.8, "diligencia": 0.9},
    )
    memory = MemoryPacket(run_id=run_id, confidence=0.8)
    crystal = Crystal().regulate(signals, memory, history=bodega.list_recent_crystals(limit=5))
    bodega.store_crystal(crystal)

    with bodega._connect() as conn:
        row = conn.execute("SELECT * FROM crystal_states WHERE run_id = ?", (run_id,)).fetchone()

    assert row["pv7_score"] == crystal.pv7_score
    assert row["stability"] == crystal.stability
    assert row["intensity"] == crystal.intensity
    assert row["q_crystal"] == crystal.q_crystal
    assert "virtue_alignment" in row["ethics_vector"]
    assert "Cristal v2" in row["regulation_notes"]
    assert row["previous_q_crystal"] == base.q_crystal
    assert row["temporal_status"] in {"stable", "improving", "degrading", "critical"}
    assert row["history_window"] == 1
    assert bodega.list_recent_crystals(limit=2)[0]["run_id"] == run_id


def test_migrate_existing_crystal_table_adds_temporal_columns(tmp_path) -> None:
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

    assert {"q_crystal", "ethics_vector", "regulation_notes"}.issubset(columns)
    assert TEMPORAL_COLUMNS.issubset(columns)
