from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from triade.runtime.runtime_recovery import RuntimeRecovery
from triade.runtime.service_health import ServiceHealth
from triade.runtime.task_leases import AutonomousTaskStore
from triade.runtime.watchdog import RuntimeWatchdog


def _healthy_db(path):
    AutonomousTaskStore(path)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE worker_tasks(id INTEGER PRIMARY KEY,status TEXT,created_at TEXT);
        CREATE TABLE worker_runs(id INTEGER PRIMARY KEY,status TEXT,started_at TEXT,finished_at TEXT);
        CREATE TABLE worker_state(key TEXT,updated_at TEXT,value_json TEXT);
        CREATE TABLE worker_events(id INTEGER PRIMARY KEY,status TEXT,created_at TEXT);
        """)
        conn.execute(
            "INSERT INTO worker_state VALUES('workers',?, '{}')",
            (datetime.now(timezone.utc).isoformat(),),
        )


def test_health_detects_stopped_process(tmp_path, monkeypatch):
    path = tmp_path / "health.db"
    _healthy_db(path)
    monkeypatch.setattr(
        "triade.runtime.service_health.build_resource_probe",
        lambda: {
            "disk": {"free_gb": 10},
            "memory": {"available_gb": 10},
            "thermal": {"thermal_status": "ok"},
        },
    )
    status = ServiceHealth(path).inspect(
        process_running=False, ollama_probe={"ok": True}
    )
    assert status.state == "stopped"
    assert "process_stopped" in status.reasons


def test_health_detects_frozen_heartbeat(tmp_path, monkeypatch):
    path = tmp_path / "health.db"
    _healthy_db(path)
    stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE worker_state SET updated_at=?", (stale,))
    monkeypatch.setattr(
        "triade.runtime.service_health.build_resource_probe",
        lambda: {
            "disk": {"free_gb": 10},
            "memory": {"available_gb": 10},
            "thermal": {"thermal_status": "ok"},
        },
    )
    status = ServiceHealth(path, heartbeat_stale_seconds=10).inspect(
        process_running=True, ollama_probe={"ok": True}
    )
    assert status.state == "stalled"
    assert "heartbeat_stale" in status.reasons


def test_recovery_snapshots_recovers_lease_and_checks_heartbeat(tmp_path):
    path = tmp_path / "health.db"
    store = AutonomousTaskStore(path)
    task = store.enqueue("research", {}, idempotency_key="recover")
    store.claim("dead")
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE autonomous_tasks SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE task_id=?",
            (task["task_id"],),
        )
    recovery = RuntimeRecovery(path, tmp_path / "snapshots").recover(
        "test", verify_heartbeat=lambda: True
    )
    assert recovery["state"] == "runtime_recovered"
    assert (tmp_path / "snapshots" / f"{recovery['recovery_id']}.db").is_file()
    assert store.get(task["task_id"])["status"] == "recovered"


def test_watchdog_honors_recovery_budget(tmp_path, monkeypatch):
    path = tmp_path / "health.db"
    _healthy_db(path)
    monkeypatch.setattr(
        "triade.runtime.service_health.build_resource_probe",
        lambda: {
            "disk": {"free_gb": 10},
            "memory": {"available_gb": 10},
            "thermal": {"thermal_status": "ok"},
        },
    )
    watchdog = RuntimeWatchdog(path, max_recoveries=1)
    first = watchdog.tick(
        process_running=False, ollama_probe={"ok": True}, verify_heartbeat=lambda: True
    )
    second = watchdog.tick(
        process_running=False, ollama_probe={"ok": True}, verify_heartbeat=lambda: True
    )
    assert first["recovery"]["state"] == "runtime_recovered"
    assert second["recovery"]["reason"] == "recovery_budget_exhausted"
