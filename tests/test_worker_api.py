"""API FastAPI para Living Workers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.routes import api as routes_api
from apps.single_port_app import app
from triade.workers.background_service import WorkerBackgroundService

client = TestClient(app)


def test_workers_api_run_once_status_queue_events(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(routes_api, "WorkerBackgroundService", lambda: WorkerBackgroundService(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs"))

    run = client.post("/workers/run-once")
    status = client.get("/workers/status")
    queue = client.get("/workers/queue")
    events = client.get("/workers/events")

    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert status.json()["last_run"]["run_ref"] == run.json()["run_ref"]
    assert queue.json()["count"] >= 1
    assert events.json()["count"] >= 1


def test_workers_api_learning_pending_and_neuron_activity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(routes_api, "WorkerBackgroundService", lambda: WorkerBackgroundService(db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs"))
    client.post("/workers/run-once")

    pending = client.get("/learning/pending")
    activity = client.get("/neurons/activity")

    assert pending.status_code == 200
    assert "candidates" in pending.json()
    assert activity.status_code == 200
    assert "activity" in activity.json()
