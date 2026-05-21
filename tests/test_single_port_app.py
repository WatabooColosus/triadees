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
