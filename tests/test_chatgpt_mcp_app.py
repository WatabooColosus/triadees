"""MCP-specific smoke and security tests; no production Bodega is used."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mcp")  # MCP stays an optional runtime dependency.

bridge = importlib.import_module("apps.chatgpt_mcp_app")


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "triade-smoke-test", "version": "1.0"},
    },
}


def _headers(auth: str | None = None) -> dict[str, str]:
    headers = {"Accept": "application/json, text/event-stream"}
    if auth:
        headers["Authorization"] = "Bearer " + auth
    return headers


def test_mcp_liveness_does_not_claim_original_runtime():
    with TestClient(bridge.app, base_url="http://localhost") as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "service": "triade-mcp-gateway"}


def test_mcp_rejects_missing_or_invalid_token(monkeypatch):
    monkeypatch.setenv("TRIADE_ACTIONS_TOKEN", "test-mcp-token")
    with TestClient(bridge.app, base_url="http://localhost") as client:
        assert client.post("/mcp", json=INIT, headers=_headers()).status_code == 401
        assert (
            client.post("/mcp", json=INIT, headers=_headers("wrong")).status_code == 401
        )


def test_mcp_rejects_when_token_not_configured(monkeypatch):
    monkeypatch.delenv("TRIADE_ACTIONS_TOKEN", raising=False)
    with TestClient(bridge.app, base_url="http://localhost") as client:
        result = client.post("/mcp", json=INIT, headers=_headers("anything"))
        assert result.status_code == 503


def test_mcp_authenticated_initialize_and_list_tools(monkeypatch):
    monkeypatch.setenv("TRIADE_ACTIONS_TOKEN", "test-mcp-token")
    headers = _headers("test-mcp-token")
    with TestClient(bridge.app, base_url="http://localhost") as client:
        initialized = client.post("/mcp", json=INIT, headers=headers)
        assert initialized.status_code == 200, initialized.text[:500]
        assert initialized.json().get("result")
        listed = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=headers,
        )
        assert listed.status_code == 200, listed.text[:500]
        tools = listed.json()["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert names == {"triade_estado", "triade_aprendizaje", "triade_ejecutar"}


def test_mcp_public_host_must_be_explicit(monkeypatch):
    monkeypatch.setenv("TRIADE_MCP_PUBLIC_HOST", "triade.example.com")
    allowed = bridge._allowlisted_hosts()
    assert "triade.example.com" in allowed
    assert "*" not in allowed
    monkeypatch.setenv("TRIADE_MCP_PUBLIC_HOST", "*.example.com")
    with pytest.raises(ValueError, match="bare DNS name"):
        bridge._allowlisted_hosts()
