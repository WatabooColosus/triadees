from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.routes import health


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(health.router)
    return TestClient(app)


def test_live_reports_process(monkeypatch):
    monkeypatch.setenv("TRIADE_CLOUD_MODE", "1")
    response = _client().get("/health/live")
    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": "triade-omega",
        "cloud_mode": True,
    }


def test_ready_accepts_writable_storage_without_optional_services(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TRIADE_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("TRIADE_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    response = _client().get("/health/ready")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"]["memory"]["ok"] is True
    assert payload["checks"]["runs"]["ok"] is True
    assert payload["checks"]["postgres"]["reason"] == "not_configured"
    assert payload["checks"]["valkey"]["reason"] == "not_configured"


def test_deep_includes_runtime_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIADE_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("TRIADE_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(
        health, "build_deep_runtime_health", lambda: {"status": "ok", "pulse": 1}
    )

    response = _client().get("/health/deep")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "healthy"
    assert payload["ready"] is True
    assert payload["heartbeat_ok"] is True
    assert payload["heartbeat"]["pulse"] == 1


def test_deep_accepts_governed_model_fallback(monkeypatch):
    monkeypatch.setattr(
        health,
        "build_deep_runtime_health",
        lambda: {
            "status": "ok",
            "checks": {"ollama_blood": True},
            "ollama_blood": {
                "status": "degraded_no_ollama",
                "can_reason": False,
                "fallback_mode": True,
            },
        },
    )

    response = _client().get("/health/deep")
    assert response.status_code == 200
    assert response.json()["heartbeat"]["ollama_blood"]["can_reason"] is False
