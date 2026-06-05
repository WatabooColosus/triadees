"""Tests del portal de emparejamiento federado."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps import federation_pairing_app
from apps.federation_pairing_app import app


def test_pairing_requires_token_and_registers_browser_node(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(federation_pairing_app, "DB_PATH", str(tmp_path / "triade.db"))
    monkeypatch.setattr(federation_pairing_app, "PAIRING_TOKEN", "test-token")
    client = TestClient(app)

    blocked = client.post(
        "/api/pair",
        json={"token": "wrong", "display_name": "Celular", "permissions": ["publish_capabilities"], "capabilities": {}},
    )
    assert blocked.status_code == 401

    response = client.post(
        "/api/pair",
        json={
            "token": "test-token",
            "display_name": "Celular Test",
            "permissions": ["publish_capabilities", "request_compute"],
            "capabilities": {
                "hardware_concurrency": 8,
                "device_memory_gb": 4,
                "user_agent": "test-browser",
                "platform": "android",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["node"]["status"] == "active"
    assert payload["node"]["capabilities"]["browser_node"] is True
    assert "request_compute" in payload["node"]["permissions"]


def test_pairing_app_exposes_repo_info() -> None:
    client = TestClient(app)

    response = client.get("/api/repo")

    assert response.status_code == 200
    payload = response.json()
    assert payload["origin"] == "https://github.com/WatabooColosus/triadees.git"
    assert payload["branch"]


def test_pairing_app_serves_termux_bootstrap(monkeypatch) -> None:
    monkeypatch.setattr(federation_pairing_app, "PAIRING_TOKEN", "secret-pair-token")
    client = TestClient(app)

    response = client.get("/downloads/termux-bootstrap.sh")

    assert response.status_code == 200
    assert "https://github.com/WatabooColosus/triadees.git" in response.text
    assert 'git clone "$REPO_URL" "$APP_DIR"' in response.text
    assert "apps/mobile_node_agent.py" in response.text
    assert "triade-mobile-8790" in response.text
    assert "secret-pair-token" not in response.text


def test_admin_page_includes_single_install_command(monkeypatch) -> None:
    monkeypatch.setattr(federation_pairing_app, "PAIRING_TOKEN", "secret-pair-token")
    client = TestClient(app)

    response = client.get("/admin")

    assert response.status_code == 200
    assert "curl -fsSL http://testserver/downloads/termux-bootstrap.sh | bash" in response.text
    assert "secret-pair-token" not in response.text
