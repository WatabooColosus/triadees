"""Tests del agente movil Termux."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.mobile_node_agent import AgentConfig, agent, app


def test_mobile_agent_admin_is_disabled_by_default() -> None:
    assert AgentConfig().admin_enabled is False


def test_mobile_agent_requires_token_and_runs_job() -> None:
    previous = agent.config.token
    agent.config.token = "test-token"
    client = TestClient(app)

    blocked = client.get("/capabilities")
    assert blocked.status_code == 401

    headers = {"Authorization": "Bearer test-token"}
    config = client.post("/config", headers=headers, json={"target_usage_percent": 60, "max_workers": 1})
    assert config.status_code == 200
    assert config.json()["target_usage_percent"] == 60

    capabilities = client.get("/capabilities", headers=headers)
    assert capabilities.status_code == 200
    assert capabilities.json()["target_usage_percent"] == 60

    submitted = client.post("/jobs", headers=headers, json={"task": "sha256", "payload": {"hello": "triade"}})
    assert submitted.status_code == 200
    job_id = submitted.json()["job_id"]

    for _ in range(30):
        job = client.get(f"/jobs/{job_id}", headers=headers).json()
        if job["status"] == "completed":
            break
    assert job["status"] == "completed"
    assert "sha256" in job["result"]

    agent.config.token = previous


def test_mobile_agent_admin_is_token_scoped_and_root_limited(tmp_path) -> None:
    previous_token = agent.config.token
    previous_root = agent.config.admin_root
    previous_enabled = agent.config.admin_enabled
    previous_commands = agent.config.allowed_commands
    agent.config.token = "admin-token"
    agent.config.admin_root = str(tmp_path)
    agent.config.admin_enabled = True
    agent.config.allowed_commands = {"python_version": ["python", "--version"]}
    (tmp_path / "note.txt").write_text("hola triade", encoding="utf-8")
    client = TestClient(app)

    assert client.get("/admin/files").status_code == 401
    headers = {"Authorization": "Bearer admin-token"}

    listed = client.get("/admin/files", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["entries"][0]["name"] == "note.txt"

    read = client.get("/admin/files/read", params={"path": "note.txt"}, headers=headers)
    assert read.status_code == 200
    assert read.json()["content"] == "hola triade"

    escape = client.get("/admin/files/read", params={"path": "../outside.txt"}, headers=headers)
    assert escape.status_code == 400

    blocked = client.post("/admin/commands/not_allowed", headers=headers)
    assert blocked.status_code == 400

    allowed = client.post("/admin/commands/python_version", headers=headers)
    assert allowed.status_code == 200
    assert allowed.json()["returncode"] == 0

    agent.config.token = previous_token
    agent.config.admin_root = previous_root
    agent.config.admin_enabled = previous_enabled
    agent.config.allowed_commands = previous_commands
