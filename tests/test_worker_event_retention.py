"""Retención básica de worker_events."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.workers.state_store import WorkerStateStore


def make_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "triade.db"
    schema = Path("triade/memory/schemas.sql").read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema)
    return db_path


def test_worker_events_are_pruned_to_retention_limit(tmp_path: Path, monkeypatch) -> None:
    db_path = make_db(tmp_path)
    monkeypatch.setenv("TRIADE_WORKER_EVENTS_RETENTION", "3")
    store = WorkerStateStore(db_path=db_path)

    for index in range(6):
        store.record_event("test_event", f"event {index}", payload={"index": index})

    events = store.list_events(limit=10)
    assert len(events) == 3
    assert [event["message"] for event in reversed(events)] == ["event 3", "event 4", "event 5"]
