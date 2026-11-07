"""Public MCP must connect without secrets yet expose no private Tríade data."""

from __future__ import annotations

import importlib

import httpx
import pytest
from fastapi.testclient import TestClient

mcp = pytest.importorskip("mcp")

public = importlib.import_module("apps.triade_public_mcp_app")


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "triade-observatory-test", "version": "1.0"},
    },
}

HEADERS = {"Accept": "application/json, text/event-stream"}


def test_public_mcp_health_and_initialize():
    with TestClient(public.build_public_app(), base_url="http://localhost") as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["service"] == "triade-omega-public-mcp"
        init = client.post("/mcp", json=INIT, headers=HEADERS)
        assert init.status_code == 200
        assert init.json().get("result")
        listed = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=HEADERS,
        )
        assert listed.status_code == 200, listed.text
        names = {t["name"] for t in listed.json()["result"]["tools"]}
        assert names == {
            "triade_estado_publico",
            "triade_codigo_publico",
            "triade_plan_publico",
        }
        assert not any("ejecutar" in name or "bodega" in name for name in names)


def test_public_mcp_reports_no_real_runtime():
    with TestClient(public.build_public_app(), base_url="http://localhost") as client:
        result = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "triade_estado_publico", "arguments": {}},
            },
            headers=HEADERS,
        )
        assert result.status_code == 200
        text = str(result.json())
        assert "runtime_original_conectado" in text
        assert "False" in text or "false" in text


def test_public_github_reports_evidence_and_fails_closed(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "sha": "b" * 40,
                "commit": {"committer": {"date": "2026-11-06T21:00:00Z"}},
            }

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, url, headers):
            assert url == (
                "https://api.github.com/repos/WatabooColosus/triadees/commits/main"
            )
            return FakeResponse()

    monkeypatch.setattr(public.httpx, "Client", FakeClient)
    evidence = public._public_git_status()
    assert evidence["verified"] is True
    assert evidence["main_commit"] == "b" * 40

    class FailedClient(FakeClient):
        def get(self, url, headers):
            raise httpx.ConnectError("unavailable")

    monkeypatch.setattr(public.httpx, "Client", FailedClient)
    unavailable = public._public_git_status()
    assert unavailable["verified"] is False
    assert unavailable["api_error_type"] == "ConnectError"
    assert unavailable["feed_error_type"] == "ConnectError"
    assert "main_commit" not in unavailable

    class RateLimitedResponse:
        status_code = 403

        def raise_for_status(self):
            request = httpx.Request(
                "GET",
                "https://api.github.com/repos/WatabooColosus/triadees/commits/main",
            )
            raise httpx.HTTPStatusError(
                "rate limit",
                request=request,
                response=httpx.Response(403, request=request),
            )

    class FeedResponse:
        def raise_for_status(self):
            return None

        text = (
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            '<link href="https://github.com/WatabooColosus/triadees/commit/'
            + "a" * 40
            + '"/></entry></feed>'
        )

    class FallbackClient(FakeClient):
        def get(self, url, headers):
            if url.startswith("https://api.github.com/"):
                return RateLimitedResponse()
            assert url == (
                "https://github.com/WatabooColosus/triadees/commits/main.atom"
            )
            return FeedResponse()

    monkeypatch.setattr(public.httpx, "Client", FallbackClient)
    recovered = public._public_git_status()
    assert recovered["verified"] is True
    assert recovered["source"] == "public_github_atom"
    assert recovered["api_http_status"] == 403
    assert recovered["main_commit"] == "a" * 40
