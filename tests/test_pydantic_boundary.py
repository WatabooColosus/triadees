"""Tests para Pydantic boundary en endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _get_client():
    from apps.single_port_app import app
    return TestClient(app, raise_server_exceptions=False)


def test_living_report_full():
    """GET /api/system/living-report returns full payload."""
    client = _get_client()
    resp = client.get("/api/system/living-report")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "runtime_continuity_score" in data
    assert "bodega_global_context_summary" in data


def test_living_report_summary():
    """GET /api/system/living-report?summary=true returns validated summary."""
    client = _get_client()
    resp = client.get("/api/system/living-report?summary=true")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "runtime_continuity_score" in data
    assert "bodega_global_context_summary" in data
    assert "stable_neuron_audit" in data


def test_observability_includes_memory_trace():
    """GET /api/observability includes memory_trace."""
    client = _get_client()
    resp = client.get("/api/observability")
    assert resp.status_code == 200
    data = resp.json()
    assert "memory_trace" in data
    assert "last_run" in data


def test_bodega_global_context():
    """GET /api/bodega/global-context returns valid response."""
    client = _get_client()
    resp = client.get("/api/bodega/global-context")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "memory_confidence" in data
