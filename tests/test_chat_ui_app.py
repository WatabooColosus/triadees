"""Tests de interfaz web local unificada de chat."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.chat_ui_app import app


client = TestClient(app)


def test_chat_ui_serves_html() -> None:
    response = client.get("/ui")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Tríade Ω" in response.text
    assert "/api/run" in response.text
    assert "/api/router/doctor" in response.text
    assert "Model Router" in response.text
