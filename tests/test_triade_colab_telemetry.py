"""Proofs for the ephemeral, authenticated outbound Colab telemetry relay."""

from __future__ import annotations

import importlib
import json
import time

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

relay = importlib.import_module("apps.triade_colab_telemetry")
public = importlib.import_module("apps.triade_public_mcp_app")

INGEST_TOKEN = "ingest-" + "t" * 48
OPERATOR_TOKEN = "operator-" + "o" * 48


@pytest.fixture(autouse=True)
def clear_ephemeral_state():
    with relay._lock:
        relay._last = None
        relay._last_clock = 0
    yield
    with relay._lock:
        relay._last = None
        relay._last_clock = 0


def _client():
    return TestClient(public.build_public_app(), base_url="http://localhost")


def _headers(token: str):
    return {"Authorization": "Bearer " + token}


def _report():
    return {
        "schema_version": 1,
        "observations": {
            "api_server_alive": True,
            "runtime_enabled": True,
            "workers_active": False,
            "heartbeat_cycle": 24,
            "mode": "observe_only",
        },
        "stats": {"cycles_last_24h": 8, "candidates_consolidated": 2},
    }


def test_ingest_and_operator_endpoints_fail_closed(monkeypatch):
    monkeypatch.delenv("TRIADE_TELEMETRY_INGEST_TOKEN", raising=False)
    monkeypatch.setenv("TRIADE_TABLET_OPERATOR_TOKEN", OPERATOR_TOKEN)
    with _client() as web:
        missing = web.post(
            "/api/telemetry/ingest", headers=_headers(INGEST_TOKEN), json=_report()
        )
        assert missing.status_code == 503
        assert web.get("/api/private/telemetry").status_code == 401
    monkeypatch.setenv("TRIADE_TELEMETRY_INGEST_TOKEN", INGEST_TOKEN)
    with _client() as web:
        invalid = web.post(
            "/api/telemetry/ingest", headers=_headers("wrong"), json=_report()
        )
        assert invalid.status_code == 401
        empty = web.get("/api/private/telemetry", headers=_headers(OPERATOR_TOKEN))
        assert empty.status_code == 200
        assert empty.json()["status"] == "no_reports"
        assert empty.json()["fresh"] is False


def test_ingest_filters_and_readout_never_claims_certification(monkeypatch):
    monkeypatch.setenv("TRIADE_TELEMETRY_INGEST_TOKEN", INGEST_TOKEN)
    monkeypatch.setenv("TRIADE_TABLET_OPERATOR_TOKEN", OPERATOR_TOKEN)
    with _client() as web:
        accepted = web.post(
            "/api/telemetry/ingest", headers=_headers(INGEST_TOKEN), json=_report()
        )
        assert accepted.status_code == 200
        assert accepted.json() == {"accepted": True, "certified": False}
        assert "no-store" in accepted.headers["cache-control"]
        status = web.get("/api/private/telemetry", headers=_headers(OPERATOR_TOKEN))
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "fresh"
        assert body["fresh"] is True
        assert body["observations"]["workers_active"] is False
        assert body["stats"]["candidates_consolidated"] == 2
        assert body["runtime_original_conectado"] is None
        assert body["runtime_identity_certified"] is False
        assert body["full_runtime_verified"] is False
        assert body["full_learning_certified"] is False
        assert body["writes_enabled"] is False
        assert INGEST_TOKEN not in status.text
        assert OPERATOR_TOKEN not in status.text


def test_ingest_drops_invalid_and_private_payloads(monkeypatch):
    monkeypatch.setenv("TRIADE_TELEMETRY_INGEST_TOKEN", INGEST_TOKEN)
    with _client() as web:
        invalid_cases = [
            {"schema_version": 1, "observations": {"private_data": 3}, "stats": {}},
            {"schema_version": 1, "observations": {"api_server_alive": 1}, "stats": {}},
            {
                "schema_version": 1,
                "observations": {"mode": "candidate secret"},
                "stats": {},
            },
            {
                "schema_version": 1,
                "observations": {"api_server_alive": True},
                "stats": {"cycles_last_24h": True},
            },
            {**_report(), "bodega": {"content": "secret"}},
            {"schema_version": 1, "observations": [], "stats": {}},
        ]
        for payload in invalid_cases:
            response = web.post(
                "/api/telemetry/ingest",
                headers=_headers(INGEST_TOKEN),
                json=payload,
            )
            assert response.status_code == 400
            assert "secret" not in response.text.lower()
        oversized = web.post(
            "/api/telemetry/ingest",
            headers=_headers(INGEST_TOKEN),
            content=json.dumps({"blob": "x" * 6000}),
            json=None,
        )
        assert oversized.status_code in (413, 415)
        assert relay._snapshot()["status"] == "no_reports"


def test_stale_telemetry_is_not_exposed_as_current(monkeypatch):
    monkeypatch.setenv("TRIADE_TELEMETRY_INGEST_TOKEN", INGEST_TOKEN)
    monkeypatch.setenv("TRIADE_TABLET_OPERATOR_TOKEN", OPERATOR_TOKEN)
    with _client() as web:
        accepted = web.post(
            "/api/telemetry/ingest",
            json=_report(),
            headers=_headers(INGEST_TOKEN),
        )
        assert accepted.status_code == 200
        with relay._lock:
            relay._last_clock = time.monotonic() - relay.FRESH_SECONDS - 1
        stale = web.get("/api/private/telemetry", headers=_headers(OPERATOR_TOKEN))
        assert stale.status_code == 200
        assert stale.json()["status"] == "stale"
        assert stale.json()["fresh"] is False
        assert "observations" not in stale.json()
        assert "stats" not in stale.json()


def test_no_write_or_shell_tools_added(monkeypatch):
    monkeypatch.setenv("TRIADE_TELEMETRY_INGEST_TOKEN", INGEST_TOKEN)
    monkeypatch.setenv("TRIADE_TABLET_OPERATOR_TOKEN", OPERATOR_TOKEN)
    with _client() as web:
        assert web.post("/api/private/telemetry").status_code == 405
        assert web.get("/api/telemetry/ingest").status_code == 405
        assert web.post("/api/run", json={"text": "bad"}).status_code == 404
        status = web.get("/api/public/status")
        assert status.json()["runtime_original_conectado"] is False
