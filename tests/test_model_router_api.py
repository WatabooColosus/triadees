"""Tests de API de Model Router (unificada en single_port_app)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.single_port_app import app


client = TestClient(app)


def test_model_router_api_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["entity"] == "Tríade Ω"
    assert payload["mode"] == "single-port"
    assert payload["port"] == 8010
    assert "ollama" in payload
    assert "hardware" in payload


def test_model_router_api_doctor() -> None:
    response = client.get("/api/models/doctor", params={"intent": "analyze", "urgency": "medium"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "router" in payload
    assert "decisions" in payload["router"]
