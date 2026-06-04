"""Tests de Tríade Single Port App."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.single_port_app import app


client = TestClient(app)


def test_single_port_ui_serves_html() -> None:
    response = client.get("/ui")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Tríade Ω Single Port" in response.text
    assert "/api/run" in response.text
    assert "/api/router/doctor" in response.text
    assert "Pulso vivo" in response.text
    assert "Herramientas ocasionales" in response.text
    assert "/api/system/model-capacity" in response.text


def test_single_port_health() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "single-port"
    assert payload["port"] == 8010
    assert "hardware" in payload
    assert "doctor" in payload


def test_single_port_router_doctor() -> None:
    response = client.post("/api/router/doctor", json={"intent": "analyze", "urgency": "medium"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "single-port"
    assert "hardware" in payload
    assert "router" in payload
    assert "decisions" in payload["router"]


def test_single_port_model_compatibility() -> None:
    response = client.get("/api/models/compatibility")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "single-port"
    assert "matrix" in payload
    assert "models" in payload["matrix"]
    assert "counts" in payload["matrix"]


def test_single_port_model_install_queue() -> None:
    response = client.get("/api/models/install-queue")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "install-queue"
    assert "policy" in payload
    assert payload["policy"]["auto_install"] is False
    assert "candidates" in payload


def test_single_port_model_capacity() -> None:
    response = client.get("/api/system/model-capacity")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["mode"] == "model-capacity"
    assert "local" in payload
    assert "federation" in payload
    assert "missing_for_comfortable_models" in payload["local"]
    assert "nodes" in payload["federation"]
    assert "observers" not in payload["federation"]
    assert "constants" in payload


def test_single_port_run_accepts_auto_select_models() -> None:
    response = client.post(
        "/api/run",
        json={
            "text": "Prueba auto selección desde single port",
            "use_ollama": False,
            "hypothalamus_model": "",
            "central_model": "",
            "auto_select_models": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"]
    assert "model_selection" in payload
