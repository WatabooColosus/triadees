"""Explicit temporary SQLite fixtures, never production activity evidence."""

from types import SimpleNamespace

from tools import triade_colab_audit as audit
from triade.db import sqlite3


def test_schema_count_avoids_sqlite_quoted_literal_and_text_ids(tmp_path):
    db = tmp_path / "fixture.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE metabolic_cycle(cycle_id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO metabolic_cycle VALUES (1274)")
        conn.execute("CREATE TABLE runtime_health_snapshots(snapshot_id TEXT)")
        conn.execute("INSERT INTO runtime_health_snapshots VALUES ('uuid')")
    counts, notes = audit.snapshot(db)
    assert counts["metabolic_cycle"] == 1
    assert counts["runtime_health_snapshots"] == 1
    assert counts["worker_events"] is None
    assert notes["worker_events"] == "table_missing"


def test_window_records_events_without_claiming_learning_or_writing(
    tmp_path, monkeypatch
):
    db = tmp_path / "fixture.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE worker_events(id INTEGER PRIMARY KEY, event_type TEXT, payload_json TEXT)"
        )
        conn.execute("CREATE TABLE autonomous_tasks(id INTEGER, status TEXT)")
        conn.execute("INSERT INTO autonomous_tasks VALUES (1, 'pending')")

    def advance(_seconds):
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO worker_events VALUES (1, 'heartbeat', 'secret fixture payload')"
            )

    monkeypatch.setattr(audit.time, "sleep", advance)
    monkeypatch.setattr(audit, "endpoint", lambda path: {"status": "not_observed"})
    runtime = SimpleNamespace(DB=db, WORK=tmp_path)
    audit.install(runtime)
    result = runtime.audit_progress(30)
    assert result["deltas"]["worker_events"] == 1
    assert result["full_certified"] is False
    assert result["details"]["worker_events"] == [{"id": 1, "event_type": "heartbeat"}]
    assert result["after"]["autonomous_tasks_statuses"] == {"pending": 1}
    assert "secret fixture payload" not in str(result)
    monkeypatch.setattr(audit.time, "sleep", lambda seconds: None)
    original = db.read_bytes()
    runtime.audit_progress(0)
    assert db.read_bytes() == original
