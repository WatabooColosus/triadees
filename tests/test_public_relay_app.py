"""Tests del relay publico de nodos web."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps import public_relay_app
from apps.public_relay_app import app


def test_public_relay_registers_node_and_completes_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(public_relay_app, "DB_PATH", tmp_path / "relay.db")
    monkeypatch.setattr(public_relay_app, "PAIRING_TOKEN", "pair")
    monkeypatch.setattr(public_relay_app, "ADMIN_TOKEN", "admin")
    client = TestClient(app)

    registered = client.post(
        "/api/register",
        json={
            "pairing_token": "pair",
            "display_name": "Celular web",
            "capabilities": {"hardware_concurrency": 8, "platform": "android"},
        },
    )
    assert registered.status_code == 200
    node = registered.json()

    headers = {"Authorization": "Bearer admin"}
    nodes = client.get("/api/nodes", headers=headers)
    assert nodes.status_code == 200
    assert nodes.json()["nodes"][0]["display_name"] == "Celular web"

    created = client.post(
        "/api/jobs",
        headers=headers,
        json={"node_id": node["node_id"], "task": "echo", "payload": {"hello": "triade"}},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    next_job = client.get("/api/jobs/next", params={"node_id": node["node_id"], "node_token": node["node_token"]})
    assert next_job.status_code == 200
    assert next_job.json()["job"]["job_id"] == job_id

    result = client.post(
        f"/api/jobs/{job_id}/result",
        json={
            "node_id": node["node_id"],
            "node_token": node["node_token"],
            "status": "completed",
            "result": {"echo": {"hello": "triade"}},
        },
    )
    assert result.status_code == 200

    jobs = client.get("/api/jobs", headers=headers)
    assert jobs.json()["jobs"][0]["status"] == "completed"
