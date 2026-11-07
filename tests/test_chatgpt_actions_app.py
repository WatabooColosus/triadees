"""Isolated tests for the ChatGPT Actions bridge. No original memory is opened."""
from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from apps import chatgpt_actions_app as bridge


def setup_gateway(monkeypatch):
    monkeypatch.setenv("TRIADE_ACTIONS_TOKEN", "gateway-secret")
    monkeypatch.setenv("TRIADE_ACTIONS_UPSTREAM_URL", "http://127.0.0.1:8010")
    monkeypatch.setenv("TRIADE_ACTIONS_UPSTREAM_KEY", "runtime-secret")
    return TestClient(bridge.app)


def stub_upstream(monkeypatch, events):
    class FakeHTTPClient:
        def __init__(self, *args, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, method, url, headers, params=None, json=None):
            events.append({"method": method, "url": url, "headers": headers, "params": params, "payload": json})
            if url.endswith("/health/live"):
                return httpx.Response(200, json={"status": "ok"})
            if url.endswith("/api/runtime/heartbeat"):
                return httpx.Response(200, json={"status": "ok", "runtime_enabled": True, "workers_active": True, "heartbeat_cycle": 11, "secret": "DO-NOT-LEAK"})
            if url.endswith("/api/runtime/learning-journal"):
                return httpx.Response(200, json={"status": "ok", "total_sessions": 3, "summary": {"ready": 1}, "private_learning": ["hidden"]})
            if url.endswith("/api/run"):
                return httpx.Response(200, json={"status": "ok", "response": "Ciclo real", "run_id": "run-1", "memory_diff": {"secret": "DO-NOT-LEAK"}})
            return httpx.Response(404)

    monkeypatch.setattr(bridge.httpx, "Client", FakeHTTPClient)


def test_authentication_fails_closed(monkeypatch):
    client = setup_gateway(monkeypatch)
    assert client.get("/actions/status").status_code == 401
    assert client.get("/actions/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    monkeypatch.delenv("TRIADE_ACTIONS_TOKEN")
    assert client.get("/actions/status", headers={"Authorization": "Bearer gateway-secret"}).status_code == 503


def test_status_is_live_and_minimized(monkeypatch):
    client = setup_gateway(monkeypatch)
    events = []
    stub_upstream(monkeypatch, events)
    result = client.get("/actions/status", headers={"Authorization": "Bearer gateway-secret"})
    assert result.status_code == 200
    assert result.json()["full_runtime_verified"] is True
    assert result.json()["pulse"]["heartbeat_cycle"] == 11
    assert "DO-NOT-LEAK" not in result.text
    assert len(events) == 2
    assert all(e["headers"]["X-Triade-Api-Key"] == "runtime-secret" for e in events)


def test_learning_is_summary_only(monkeypatch):
    client = setup_gateway(monkeypatch)
    events = []
    stub_upstream(monkeypatch, events)
    result = client.get("/actions/learning?limit=5", headers={"Authorization": "Bearer gateway-secret"})
    assert result.status_code == 200
    assert result.json()["journal"]["total_sessions"] == 3
    assert "private_learning" not in result.text
    assert result.json()["full_learning_certified"] is False
    assert events[0]["params"] == {"limit": 5}
    assert client.get("/actions/learning?limit=200", headers={"Authorization": "Bearer gateway-secret"}).status_code == 422


def test_run_off_by_default_and_opt_in(monkeypatch):
    client = setup_gateway(monkeypatch)
    events = []
    stub_upstream(monkeypatch, events)
    auth = {"Authorization": "Bearer gateway-secret"}
    assert client.post("/actions/run", headers=auth, json={"text": "hola"}).status_code == 403
    assert not events
    monkeypatch.setenv("TRIADE_ACTIONS_ALLOW_RUN", "1")
    result = client.post("/actions/run", headers=auth, json={"text": "hola"})
    assert result.status_code == 200
    assert result.json()["response"] == "Ciclo real"
    assert "DO-NOT-LEAK" not in result.text
    assert events[0]["payload"]["semantic_recall_enabled"] is False
    assert events[0]["payload"]["debug"] is False


def test_upstream_must_use_https_outside_localhost(monkeypatch):
    client = setup_gateway(monkeypatch)
    monkeypatch.setenv("TRIADE_ACTIONS_UPSTREAM_URL", "http://example.org:8010")
    result = client.get("/actions/status", headers={"Authorization": "Bearer gateway-secret"})
    assert result.status_code == 503
    assert result.json()["detail"] == "upstream_not_safely_configured"


def test_public_health_does_not_claim_runtime(monkeypatch):
    client = setup_gateway(monkeypatch)
    result = client.get("/health")
    assert result.status_code == 200
    assert "runtime_enabled" not in result.text


def test_openapi_exposes_authentication(monkeypatch):
    client = setup_gateway(monkeypatch)
    schema = client.get("/openapi.json").json()
    assert "/actions/status" in schema["paths"]
    assert schema["paths"]["/actions/run"]["post"]["security"]
