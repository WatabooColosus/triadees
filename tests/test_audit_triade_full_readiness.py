"""The evidence audit reads synthetic test databases without changing them."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pytest

from tools.audit_triade_full_readiness import audit

NOW = dt.datetime(2026, 10, 22, 23, 0, tzinfo=dt.UTC)


def database(path: Path) -> Path:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE autonomous_tasks (status TEXT);
            CREATE TABLE worker_runs (
                id INTEGER PRIMARY KEY, run_ref TEXT, status TEXT,
                started_at TEXT, finished_at TEXT, summary_json TEXT
            );
            CREATE TABLE worker_events (
                id INTEGER PRIMARY KEY, run_ref TEXT,
                event_type TEXT, created_at TEXT
            );
            CREATE TABLE triade_weight_events (id INTEGER PRIMARY KEY);
            CREATE TABLE improvement_proposals (id INTEGER PRIMARY KEY);
            CREATE TABLE improvement_canaries (id INTEGER PRIMARY KEY);
            CREATE TABLE federated_nodes (id INTEGER PRIMARY KEY);
            CREATE TABLE trainable_adapters (id INTEGER PRIMARY KEY);
            """
        )
        conn.execute("INSERT INTO autonomous_tasks VALUES ('completed')")
        conn.execute("INSERT INTO triade_weight_events VALUES (1)")
        conn.execute(
            "INSERT INTO worker_runs VALUES (1,?,?,?,?,?)",
            ("test-worker", "running", "2026-10-22T22:40:00+00:00", None, '{"iterations": 0}'),
        )
        conn.execute(
            "INSERT INTO worker_events VALUES (1,?,?,?)",
            ("test-worker", "task_completed", "2026-10-22T22:59:00+00:00"),
        )
    return path


def test_audit_reports_real_rows_not_imaginary_certification(tmp_path: Path) -> None:
    path = database(tmp_path / "state.db")
    previous_size = path.stat().st_size
    summary = audit(path, now=NOW, fingerprint=True)
    assert path.stat().st_size == previous_size
    assert summary["checks"]["sqlite_integrity"] == "ok"
    assert summary["counts"]["triade_weight_events"] == 1
    assert summary["counts"]["improvement_proposals"] == 0
    assert summary["checks"]["historical_weight_updates_observed"] is True
    assert summary["checks"]["autonomous_self_improvement_circuit_certified"] is False
    assert summary["full_certification"] == "not_established"
    assert len(summary["source"]["file_sha256"]) == 64


def test_running_worker_with_events_discloses_unfinished_summary(tmp_path: Path) -> None:
    summary = audit(database(tmp_path / "state.db"), now=NOW)
    assert summary["worker"]["completed_task_events_in_run"] == 1
    assert summary["worker"]["unfinished_summary_despite_events"] is True
    assert summary["worker"]["last_event_age_seconds"] == 60
    assert "worker_summary_not_updated_while_running" in summary["gaps"]


def test_missing_tables_are_not_treated_as_zero_or_pass(tmp_path: Path) -> None:
    path = tmp_path / "blank.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE minimal (value TEXT)")
    summary = audit(path, now=NOW)
    assert summary["counts"]["improvement_proposals"] is None
    assert any(gap.startswith("missing_evidence_tables") for gap in summary["gaps"])
    assert summary["checks"]["historical_task_activity_observed"] is False


def test_unknown_file_refuses_to_create_database(tmp_path: Path) -> None:
    path = tmp_path / "absent.db"
    with pytest.raises(FileNotFoundError):
        audit(path, now=NOW)
    assert not path.exists()
