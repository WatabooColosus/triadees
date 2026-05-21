"""Tests de API independiente de Model Router."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.model_router_api import app


client = TestClient(app)


def test_model_router_api_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "triade-model-router"
    assert "roles" in payload


def test_model_router_api_doctor() -> None:
    response = client.get("/models/doctor", params={"intent": "analyze", "urgency": "medium"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "router" in payload
    assert "decisions" in payload["router"]
