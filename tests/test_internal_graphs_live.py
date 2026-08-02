from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from apps import internal_graphs_live
from apps.single_port_app import app


def test_live_snapshot_reads_real_sources_without_simulation(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "triade.db"
    connection = sqlite3.connect(db)
    connection.executescript(
        """
        CREATE TABLE runs (run_id TEXT PRIMARY KEY, status TEXT, created_at TEXT);
        CREATE TABLE autonomous_tasks (id INTEGER PRIMARY KEY, run_id TEXT, status TEXT, task_type TEXT);
        INSERT INTO runs VALUES ('real-run', 'running', '2026-08-02T23:00:00Z');
        INSERT INTO autonomous_tasks VALUES (1, 'real-run', 'running', 'observe');
        """
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("TRIADE_DB_PATH", str(db))

    snapshot = internal_graphs_live.build_live_snapshot(file_limit=50, neural_limit=50)

    assert snapshot["source"]["simulated"] is False
    assert snapshot["database"]["integrity"] == "ok"
    assert snapshot["resources"]["pid"] > 0
    assert any(node["node_id"] == "run:real-run" for node in snapshot["neural"]["nodes"])


def test_internal_graphs_ui_and_snapshot_routes(monkeypatch, tmp_path: Path) -> None:
    db = tmp_path / "triade.db"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, status TEXT)")
    connection.commit()
    connection.close()
    monkeypatch.setenv("TRIADE_DB_PATH", str(db))
    monkeypatch.setenv("TRIADE_DISABLE_BACKGROUND", "1")

    with TestClient(app) as client:
        ui = client.get("/internal-graphs")
        snapshot = client.get("/api/internal-graphs/snapshot")

    assert ui.status_code == 200
    assert "EventSource('/api/internal-graphs/stream')" in ui.text
    assert snapshot.status_code == 200
    assert snapshot.json()["source"]["simulated"] is False
