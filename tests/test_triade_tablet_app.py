"""Safety and functional tests for Tríade's public tablet console."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

public = importlib.import_module("apps.triade_public_mcp_app")


def test_tablet_home_assets_and_security_headers():
    with TestClient(public.build_public_app(), base_url="http://localhost") as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "Tríade Ω · Centro de Control" in home.text
        assert 'id="plan-form"' in home.text
        assert 'id="history-list"' in home.text
        assert "Bodega original" in home.text
        assert home.headers["cache-control"] == "no-store"
        assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
        assert "script-src 'self'" in home.headers["content-security-policy"]
        for path, expect in (
            ("/ui.css", "@media"),
            ("/ui.js", "api/public/plan"),
            ("/sw.js", "api"),
            ("/manifest.webmanifest", "standalone"),
            ("/icon.svg", "<svg"),
        ):
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code)
            assert expect in response.text


def test_tablet_public_status_is_observatory_not_original_runtime():
    with TestClient(public.build_public_app(), base_url="http://localhost") as client:
        response = client.get("/api/public/status")
        assert response.status_code == 200
        data = response.json()
        assert data["operativo"] is True
        assert data["runtime_original_conectado"] is False
        assert data["bodega_original_conectada"] is False
        assert data["escrituras_habilitadas"] is False
        assert response.headers["cache-control"] == "no-store"
        wrong_content_type = client.post(
            "/api/public/plan",
            content="not a json",
            headers={"Content-Type": "text/plain"},
        )
        assert wrong_content_type.status_code == 415

        invalid_json = client.post(
            "/api/public/plan",
            content="{bad json",
            headers={"Content-Type": "application/json"},
        )
        assert invalid_json.status_code == 400

        empty = client.post("/api/public/plan", json={"objetivo": ""})
        assert empty.status_code == 422

        too_long = client.post("/api/public/plan", json={"objetivo": "x" * 501})
        assert too_long.status_code == 422

        extra_fields = client.post(
            "/api/public/plan", json={"objetivo": "plan", "admin": True}
        )
        assert extra_fields.status_code == 400

        invalid_type = client.post("/api/public/plan", json={"objetivo": 42})
        assert invalid_type.status_code == 400

        over_body = client.post(
            "/api/public/plan",
            content='{"objetivo":"' + "x" * 3000 + '"}',
            headers={"Content-Type": "application/json"},
        )
        assert over_body.status_code == 413


def test_tablet_does_not_break_public_mcp_transport():
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "tablet-test", "version": "1.0"},
        },
    }
    with TestClient(public.build_public_app(), base_url="http://localhost") as client:
        reply = client.post(
            "/mcp",
            json=init,
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert reply.status_code == 200, reply.text
        assert reply.json().get("result")
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["service"] == "triade-omega-public-mcp"
