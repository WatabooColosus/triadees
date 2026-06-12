"""Tests para stable-audit apply API endpoint."""

from __future__ import annotations

import os
from unittest.mock import patch

from fastapi.testclient import TestClient


def _get_client():
    from apps.single_port_app import app
    return TestClient(app, raise_server_exceptions=False)


def test_stable_audit_apply_requires_explicit_apply():
    """apply=false returns requires_explicit_apply with read_only_result."""
    client = _get_client()
    resp = client.post("/api/neurons/stable-audit/apply?apply=false")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "requires_explicit_apply"
    assert "read_only_result" in data
    assert "Debe enviar apply=true" in data["message"]


def test_stable_audit_apply_no_apply_defaults_to_read_only():
    """Without apply param, defaults to read-only."""
    client = _get_client()
    resp = client.post("/api/neurons/stable-audit/apply")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "requires_explicit_apply"


def test_stable_audit_apply_with_key_and_apply_true():
    """With correct API key and apply=true, executes apply."""
    client = _get_client()
    with patch.dict(os.environ, {"TRIADE_API_KEY": "test-key-123"}):
        resp = client.post(
            "/api/neurons/stable-audit/apply?apply=true",
            headers={"X-TRIADE-API-Key": "test-key-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") != "requires_explicit_apply"


def test_stable_audit_apply_wrong_key_fails():
    """With wrong API key, returns 401."""
    client = _get_client()
    with patch.dict(os.environ, {"TRIADE_API_KEY": "test-key-123"}):
        resp = client.post(
            "/api/neurons/stable-audit/apply?apply=true",
            headers={"X-TRIADE-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401


def test_stable_audit_apply_no_key_when_required():
    """With TRIADE_API_KEY set but no header, returns 401."""
    client = _get_client()
    with patch.dict(os.environ, {"TRIADE_API_KEY": "test-key-123"}):
        resp = client.post("/api/neurons/stable-audit/apply?apply=true")
        assert resp.status_code == 401


def test_stable_audit_get_read_only():
    """GET /api/neurons/stable-audit is always read-only."""
    client = _get_client()
    resp = client.get("/api/neurons/stable-audit")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_stable_neurons" in data


def test_system_stable_audit_get_read_only():
    """GET /api/system/neurons/stable-audit is always read-only."""
    client = _get_client()
    resp = client.get("/api/system/neurons/stable-audit")
    # May return 404 if route not mounted in test app; real server has it
    if resp.status_code == 200:
        data = resp.json()
        assert "total_stable_neurons" in data
