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
    assert "node_token" not in nodes.json()["nodes"][0]

    created = client.post(
        "/api/jobs",
        headers=headers,
        json={"node_id": node["node_id"], "task": "echo", "payload": {"hello": "triade"}},
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    next_job = client.get(
        "/api/jobs/next",
        params={"node_id": node["node_id"]},
        headers={"Authorization": f"Bearer {node['node_token']}"},
    )
    assert next_job.status_code == 200
    assert next_job.json()["job"]["job_id"] == job_id
    assert node["node_token"] not in next_job.text

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
    assert node["node_token"] not in jobs.text

    with public_relay_app.connect() as conn:
        audit = conn.execute("SELECT * FROM relay_job_audit WHERE job_id = ?", (job_id,)).fetchone()
    assert audit is not None
    assert audit["node_id"] == node["node_id"]
    assert audit["task"] == "echo"
    assert audit["status"] == "completed"
    assert audit["created_at"] is not None
    assert audit["started_at"] is not None
    assert audit["completed_at"] is not None
    assert len(audit["payload_sha256"]) == 64
    assert len(audit["result_sha256"]) == 64
    assert "triade" not in (audit["payload_sha256"] + audit["result_sha256"])


def test_public_relay_requires_configured_tokens(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(public_relay_app, "DB_PATH", tmp_path / "relay.db")
    monkeypatch.setattr(public_relay_app, "PAIRING_TOKEN", "")
    monkeypatch.setattr(public_relay_app, "ADMIN_TOKEN", "")
    client = TestClient(app)

    registered = client.post("/api/register", json={"pairing_token": "pair", "display_name": "Nodo", "capabilities": {}})
    nodes = client.get("/api/nodes", headers={"Authorization": "Bearer admin"})

    assert registered.status_code == 503
    assert nodes.status_code == 503


def test_public_relay_rejects_invalid_bearer_for_next_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(public_relay_app, "DB_PATH", tmp_path / "relay.db")
    monkeypatch.setattr(public_relay_app, "PAIRING_TOKEN", "pair")
    monkeypatch.setattr(public_relay_app, "ADMIN_TOKEN", "admin")
    client = TestClient(app)

    node = client.post(
        "/api/register",
        json={"pairing_token": "pair", "display_name": "Nodo", "capabilities": {}},
    ).json()

    rejected = client.get(
        "/api/jobs/next",
        params={"node_id": node["node_id"]},
        headers={"Authorization": "Bearer incorrecto"},
    )

    assert rejected.status_code == 401
    assert node["node_token"] not in rejected.text


def test_public_relay_accepts_preprocess_text_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(public_relay_app, "DB_PATH", tmp_path / "relay.db")
    monkeypatch.setattr(public_relay_app, "PAIRING_TOKEN", "pair")
    monkeypatch.setattr(public_relay_app, "ADMIN_TOKEN", "admin")
    client = TestClient(app)

    node = client.post(
        "/api/register",
        json={"pairing_token": "pair", "display_name": "Tablet", "capabilities": {"hardware_concurrency": 8}},
    ).json()
    headers = {"Authorization": "Bearer admin"}

    created = client.post(
        "/api/jobs",
        headers=headers,
        json={"node_id": node["node_id"], "task": "preprocess_text", "payload": {"text": "hola triade"}},
    )

    assert created.status_code == 200
    next_job = client.get("/api/jobs/next", params={"node_id": node["node_id"], "node_token": node["node_token"]})
    assert next_job.json()["job"]["task"] == "preprocess_text"
    assert node["node_token"] not in next_job.text


def test_public_relay_serves_persistent_browser_node_ui(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(public_relay_app, "DB_PATH", tmp_path / "relay.db")
    client = TestClient(app)

    html = client.get("/").text
    manifest = client.get("/manifest.webmanifest")

    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"
    assert "triade_public_relay_node" in html
    assert "resumeStoredNode" in html
    assert "wakeLock" in html
    assert '"Authorization":"Bearer "+nodeToken' in html


def test_public_relay_recognizes_native_android_node(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(public_relay_app, "DB_PATH", tmp_path / "relay.db")
    monkeypatch.setattr(public_relay_app, "PAIRING_TOKEN", "pair")
    monkeypatch.setattr(public_relay_app, "ADMIN_TOKEN", "admin")
    client = TestClient(app)

    registered = client.post(
        "/api/register",
        json={
            "pairing_token": "pair",
            "display_name": "Android nativo",
            "capabilities": {
                "native_android": True,
                "app_node": True,
                "foreground_service": True,
                "background_execution": True,
                "cpu_count": 8,
                "ram_available_gb": 4,
                "resource_limit_percent": 100,
                "cpu_authorized_count": 8,
                "ram_authorized_gb": 4.0,
                "allowed_tasks": ["sha256", "preprocess_text"],
            },
        },
    )

    assert registered.status_code == 200
    caps = registered.json()["capabilities"]
    assert caps["native_android"] is True
    assert caps["browser_node"] is False
    assert caps["background_execution"] is True
    assert caps["tier"] == "android-native"
    assert caps["resource_limit_percent"] == 100
    assert caps["cpu_authorized_count"] == 8
    assert caps["ram_authorized_gb"] == 4.0


def test_public_relay_serves_android_download_page(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(public_relay_app, "DB_PATH", tmp_path / "relay.db")
    monkeypatch.setattr(public_relay_app, "ANDROID_APK_PATH", tmp_path / "missing.apk")
    client = TestClient(app)

    page = client.get("/downloads/android-node")
    apk = client.get("/downloads/triade-android-node.apk")

    assert page.status_code == 200
    assert "APK pendiente de compilacion" in page.text
    assert apk.status_code == 404
