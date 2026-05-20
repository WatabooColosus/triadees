"""Pruebas de la API local FastAPI de Tríade Ω."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api_app import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["entity"] == "Tríade Ω"
    assert "doctor" in payload


def test_triade_run_endpoint(tmp_path) -> None:
    response = client.post(
        "/triade/run",
        json={
            "text": "Run desde API test",
            "source": "test-api",
            "runs_dir": str(tmp_path / "runs"),
            "db_path": str(tmp_path / "triade.db"),
            "use_ollama": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"].startswith("run-")
    assert payload["memory_diff"]["stored"] is True
    assert payload["models"]["central"]["provider"] == "template"


def test_triade_recall_endpoint() -> None:
    response = client.get("/triade/recall", params={"query": "", "limit": 3})
    assert response.status_code == 200
    payload = response.json()
    assert "episodes" in payload
    assert "count" in payload


def test_triade_doctor_endpoint() -> None:
    response = client.get("/triade/doctor", params={"use_ollama": False})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "counts" in payload
