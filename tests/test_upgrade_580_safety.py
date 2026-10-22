"""Regression checks for the 5.8.0 audit and recovery utilities.

Only synthetic temporary SQLite databases are modified.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pytest

from tools.acceptance_580 import evaluate
from tools.upgrade_triade_580 import repair_leases, report


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def make_db(root: Path, *, fresh_heartbeat: bool = True) -> Path:
    db = root / "triade" / "memory" / "triade.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE autonomous_tasks (
                task_id TEXT PRIMARY KEY, task_type TEXT NOT NULL,
                status TEXT, worker_id TEXT, lease_acquired_at TEXT,
                lease_expires_at TEXT, heartbeat_at TEXT, updated_at TEXT,
                last_error TEXT
            );
            CREATE TABLE metabolic_cycle (status TEXT);
            CREATE TABLE worker_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_ref TEXT,
                status TEXT, summary_json TEXT
            );
            CREATE TABLE worker_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_ref TEXT,
                event_type TEXT
            );
            CREATE TABLE runtime_health_snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                state TEXT, reason_json TEXT, metrics_json TEXT, created_at TEXT
            );
            CREATE TABLE model_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, provider TEXT,
                model_name TEXT, ok INTEGER, error TEXT, quality_score REAL,
                created_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO autonomous_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("expired-task", "pulse_check", "running", "old-worker",
             "2000-01-01T00:00:00+00:00", "2000-01-01T00:01:00+00:00",
             None, utc_now(), None),
        )
        conn.execute(
            "INSERT INTO worker_runs (run_ref,status,summary_json) VALUES (?,?,?)",
            ("worker-demo", "running", '{"iterations": 0}'),
        )
        conn.execute(
            "INSERT INTO worker_events (run_ref,event_type) VALUES (?,?)",
            ("worker-demo", "task_completed"),
        )
        conn.execute(
            "INSERT INTO runtime_health_snapshots (state,reason_json,metrics_json,created_at) VALUES (?,?,?,?)",
            ("healthy", "[]", json.dumps({
                "heartbeat_age_seconds": 2 if fresh_heartbeat else 500,
                "last_task_transition_at": utc_now(),
            }), utc_now()),
        )
    return db


def test_running_worker_zero_summary_is_not_a_false_stall(tmp_path: Path) -> None:
    make_db(tmp_path)
    status = report(tmp_path)
    assert status["checks"]["sqlite_integrity"] == "ok"
    assert status["worker_progress"]["total_events"] == 1
    assert status["worker_progress"]["completed_events"] == 1
    assert "worker_summary_not_final" in status["findings"]
    assert "worker_reports_zero_iterations" not in status["findings"]


def test_acceptance_requires_observed_progress_not_finished_summary(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    before = report(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO worker_events (run_ref,event_type) VALUES (?,?)",
            ("worker-demo", "task_completed"),
        )
    after = report(tmp_path)
    assert after["latest_worker"]["summary_json"] == '{"iterations": 0}'
    assert evaluate(before, after)["pass"] is True
    assert evaluate(after, after)["checks"]["real_progress"] is False


def test_acceptance_rejects_stale_observation(tmp_path: Path) -> None:
    db = make_db(tmp_path, fresh_heartbeat=False)
    before = report(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO worker_events (run_ref,event_type) VALUES (?,?)",
            ("worker-demo", "task_completed"),
        )
    after = report(tmp_path)
    assert evaluate(before, after)["checks"]["heartbeat_fresh"] is False
    assert evaluate(before, after)["pass"] is False


def test_lease_repair_refuses_live_worker(tmp_path: Path) -> None:
    db = make_db(tmp_path)
    with pytest.raises(RuntimeError, match="active worker heartbeat"):
        repair_leases(tmp_path)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT status FROM autonomous_tasks").fetchone()[0] == "running"
    assert not list(db.parent.glob("triade.db.pre_5_8_0_*"))


def test_offline_lease_repair_has_consistent_wal_backup(tmp_path: Path) -> None:
    db = make_db(tmp_path, fresh_heartbeat=False)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        conn.execute(
            "INSERT INTO autonomous_tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("pending-task", "pulse_check", "pending", None,
             None, None, None, utc_now(), None),
        )
        conn.commit()
        outcome = repair_leases(tmp_path)
        assert outcome["requeued_expired_leases"] == 1
        assert outcome["backup_integrity"] == "ok"
        with sqlite3.connect(outcome["backup"]) as backed_up:
            assert backed_up.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert backed_up.execute("SELECT COUNT(*) FROM autonomous_tasks").fetchone()[0] == 2
            assert backed_up.execute("SELECT status FROM autonomous_tasks WHERE task_id='expired-task'").fetchone()[0] == "running"
        with sqlite3.connect(db) as updated:
            assert updated.execute("SELECT status FROM autonomous_tasks WHERE task_id='expired-task'").fetchone()[0] == "pending"
    finally:
        conn.close()
