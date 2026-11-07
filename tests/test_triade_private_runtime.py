"""Fail-closed protected read-only link to a real Tríade runtime.

Never uses the original database, never writes, never calls an external model.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

protected = importlib.import_module("apps.triade_private_runtime")
public = importlib.import_module("apps.triade_public_mcp_app")

LONG_SECRET = "test-only-" + "s" * 40


def client():
    return TestClient(public.build_public_app(), base_url="http://localhost")


def auth(value: str = LONG_SECRET):
    return {"Authorization": "Bearer " + value}


def test_private_read_api_fails_closed_without_long_operator_secret(monkeypatch):
    monkeypatch.delenv("TRIADE_ACTIONS_TOKEN", raising=False)
    with client() as web:
        for path in (
            "/api/private/connection",
            "/api/private/status",
            "/api/private/learning",
        ):
            response = web.get(path, headers=auth())
            assert response.status_code == 503
            assert "no-store" in response.headers["cache-control"]
            assert "runtime_upstream" not in response.text
    monkeypatch.setenv("TRIADE_ACTIONS_TOKEN", "short")
    with client() as web:
        assert web.get("/api/private/status", headers=auth()).status_code == 503


def test_unauthorized_cannot_access_original_runtime(monkeypatch):
    monkeypatch.setenv("TRIADE_ACTIONS_TOKEN", LONG_SECRET)
    monkeypatch.setenv("TRIADE_ACTIONS_UPSTREAM_URL", "https://runtime.example.net")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No private upstream calls permitted")

    monkeypatch.setattr(protected.runtime_gateway, "_upstream", forbidden)
    with client() as web:
        for path in (
            "/api/private/connection",
            "/api/private/status",
            "/api/private/learning",
        ):
            for headers in ({}, auth("incorrect-" + "a" * 40)):
                response = web.get(path, headers=headers)
                assert response.status_code == 401
                assert LONG_SECRET not in response.text
        assert web.post("/api/private/status", headers=auth()).status_code == 405


def test_authenticated_configuration_does_not_expose_upstream_details(monkeypatch):
    monkeypatch.setenv("TRIADE_ACTIONS_TOKEN", LONG_SECRET)
    monkeypatch.delenv("TRIADE_ACTIONS_UPSTREAM_URL", raising=False)
    monkeypatch.delenv("TRIADE_ACTIONS_UPSTREAM_KEY", raising=False)
    with client() as web:
        configured = web.get("/api/private/connection", headers=auth())
        assert configured.status_code == 200
        assert configured.json()["authenticated"] is True
        assert configured.json()["runtime_upstream_configured"] is False
        assert configured.json()["private_read_only"] is True
        assert configured.json()["full_runtime_verified"] is False
        assert web.get("/api/private/status", headers=auth()).status_code == 503
        assert web.get("/api/private/learning", headers=auth()).status_code == 503


def test_private_status_and_learning_are_genuine_filtered_gets(monkeypatch):
    monkeypatch.setenv("TRIADE_ACTIONS_TOKEN", LONG_SECRET)
    monkeypatch.setenv("TRIADE_ACTIONS_UPSTREAM_URL", "https://runtime.example.net")
    monkeypatch.setenv("TRIADE_ACTIONS_UPSTREAM_KEY", "secret-to-not-return")
    called = []

    def stub(method, path, *, params=None):
        called.append((method, path, params))
        if path == "/health/live":
            return {"status": "ok", "private_file": "secret"}
        if path == "/api/runtime/heartbeat":
            return {
                "status": "ok",
                "api_server_alive": True,
                "runtime_enabled": True,
                "workers_active": False,
                "can_reason": True,
                "heartbeat_cycle": 33,
                "private_file": "do-not-return",
            }
        if path == "/api/runtime/learning-journal":
            assert params == {"limit": 20}
            return {
                "status": "ok",
                "since_hours": 24,
                "cycles_last_24h": 8,
                "missions_executed": 7,
                "neuron_evidence_created": 3,
                "candidates_created": 2,
                "candidates_evaluated": 1,
                "candidates_internally_checked": 5,
                "candidates_verified_with_evidence": 0,
                "candidates_consolidated": 1,
                "candidates_rejected": 2,
                "neurons_nourished": 4,
                "semantic_documents_activity": {
                    "count": 2,
                    "latest": [{"content": "private memory"}],
                },
                "latest_events": [{"body": "sensitive personal content"}],
                "latest_learning_candidates": [{"title": "secret candidate"}],
                "truth": "Do not trust a headline without evidence",
            }
        raise AssertionError("Unexpected upstream path")

    monkeypatch.setattr(protected.runtime_gateway, "_upstream", stub)
    with client() as web:
        info = web.get("/api/private/connection", headers=auth())
        assert info.status_code == 200
        assert info.json()["runtime_upstream_configured"] is True
        assert info.json()["runtime_upstream_key_present"] is True

        status = web.get("/api/private/status", headers=auth())
        assert status.status_code == 200
        assert status.json()["runtime_original_conectado"] is True
        assert status.json()["full_runtime_verified"] is False
        assert status.json()["writes_enabled"] is False
        assert status.json()["observations"]["workers_active"] is False
        assert "private_file" not in status.text
        assert "secret" not in status.text

        learning = web.get("/api/private/learning", headers=auth())
        assert learning.status_code == 200
        body = learning.json()
        assert body["full_learning_certified"] is False
        assert body["writes_enabled"] is False
        assert body["stats"]["cycles_last_24h"] == 8
        assert body["stats"]["candidates_internally_checked"] == 5
        assert body["stats"]["semantic_documents_count"] == 2
        assert "private memory" not in learning.text
        assert "sensitive personal content" not in learning.text
        assert "secret candidate" not in learning.text
        assert LONG_SECRET not in learning.text
    assert called == [
        ("GET", "/health/live", None),
        ("GET", "/api/runtime/heartbeat", None),
        ("GET", "/api/runtime/learning-journal", {"limit": 20}),
    ]


def test_upstream_failure_keeps_truth_and_credentials_private(monkeypatch):
    monkeypatch.setenv("TRIADE_ACTIONS_TOKEN", LONG_SECRET)
    monkeypatch.setenv("TRIADE_ACTIONS_UPSTREAM_URL", "https://runtime.example.net")

    def unavailable(*_args, **_kwargs):
        raise HTTPException(status_code=502, detail="private-upstream-token")

    monkeypatch.setattr(protected.runtime_gateway, "_upstream", unavailable)
    with client() as web:
        for path in ("/api/private/status", "/api/private/learning"):
            response = web.get(path, headers=auth())
            assert response.status_code == 502
            assert response.json()["error"] == "original_runtime_connection_unavailable"
            assert "private-upstream-token" not in response.text


def test_public_status_and_mcp_do_not_expose_private_settings(monkeypatch):
    monkeypatch.setenv("TRIADE_ACTIONS_TOKEN", LONG_SECRET)
    monkeypatch.setenv("TRIADE_ACTIONS_UPSTREAM_URL", "https://runtime.example.net")
    monkeypatch.setenv("TRIADE_ACTIONS_UPSTREAM_KEY", "sensitive-upstream-secret")
    with client() as web:
        home = web.get("/")
        public_status = web.get("/api/public/status")
        assert home.status_code == 200
        assert public_status.status_code == 200
        assert public_status.json()["runtime_original_conectado"] is False
        assert LONG_SECRET not in home.text
        assert LONG_SECRET not in public_status.text
        assert "sensitive-upstream-secret" not in home.text
        assert "runtime.example.net" not in public_status.text


def test_metrics_disallow_nested_raw_content_and_bool_as_number():
    result = protected._summary_metrics(
        {
            "cycles_last_24h": 3,
            "missions_executed": True,
            "candidates_created": -1,
            "candidates_evaluated": 2.5,
            "candidates_consolidated": 4,
            "latest_events": {"content": "ignore"},
            "semantic_documents_activity": {
                "count": 9,
                "latest": ["private"],
            },
        }
    )
    assert result == {
        "cycles_last_24h": 3,
        "candidates_consolidated": 4,
        "semantic_documents_count": 9,
    }
