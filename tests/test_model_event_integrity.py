from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.bodega import Bodega


def test_model_event_creates_parent_run_for_diagnostic(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    bodega = Bodega(db_path=db_path)

    event_id = bodega.store_model_event(
        "diagnostic-model-run",
        "runtime",
        "ollama",
        "qwen2.5:3b-instruct",
        True,
    )

    assert event_id > 0
    with sqlite3.connect(db_path) as conn:
        parent = conn.execute(
            "SELECT source, status FROM runs WHERE run_id = ?",
            ("diagnostic-model-run",),
        ).fetchone()
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert parent == ("model_event", "ok")
    assert violations == []
