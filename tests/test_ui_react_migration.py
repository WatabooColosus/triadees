"""Tests para UI React SPA, legacy routes, dashboard, git status y deuda técnica."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from apps.single_port_app import app
from triade.core.repo_runtime_status import build_repo_runtime_status

client = TestClient(app, raise_server_exceptions=False)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def test_react_build_exists_or_build_instruction():
    """La SPA React build debe existir."""
    index = FRONTEND_DIST / "index.html"
    assert index.exists(), "frontend/dist/index.html no encontrado. Ejecutar npm --prefix frontend run build"
    assets = list((FRONTEND_DIST / "assets").glob("index-*.js"))
    assert len(assets) >= 1, "No hay assets JS build. Ejecutar npm --prefix frontend run build"


def test_single_port_serves_spa_index():
    """GET / debe servir el SPA index."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    assert "root" in body or "Triade" in body or "triade" in body


def test_legacy_ui_routes_deprecated():
    """Las rutas UI legacy deben ser wrappers deprecated con aviso de migración."""
    for route in ["/api/ui/clean", "/api/ui/legacy"]:
        resp = client.get(route)
        assert resp.status_code in (200, 302, 307), f"{route} returned {resp.status_code}"
        body_lower = resp.text.lower()
        assert "migrada" in body_lower or "deprecad" in body_lower or resp.status_code in (302, 307), \
            f"{route} no muestra aviso de migración ni redirige"


def test_no_new_html_embedded_routes_without_deprecation():
    """Verificar que no haya nuevas rutas HTML sin marca DEPRECATED_UI."""
    ui_html_path = Path(__file__).resolve().parent.parent / "apps/ui_html.py"
    if ui_html_path.exists():
        content = ui_html_path.read_text(encoding="utf-8")
        html_constants = sum(1 for line in content.splitlines()
                             if line.strip().startswith(("CLEAN_UI_HTML", "HTML =", "TRIADE_UI_HTML", "TRIADE_REACT_UI_HTML")))
        assert html_constants <= 4, f"apps/ui_html.py tiene {html_constants} constantes HTML legacy sin deprecar"


def test_api_runtime_heartbeat_contains_ollama_blood():
    """GET /api/runtime/heartbeat debe contener datos de Ollama Blood."""
    resp = client.get("/api/runtime/heartbeat")
    assert resp.status_code == 200
    data = resp.json()
    assert "ollama_blood" in data or "blood_pressure_score" in data or "ollama_ok" in data


def test_api_models_ollama_blood():
    """GET /api/models/ollama/blood debe responder con sangre cognitiva."""
    resp = client.get("/api/models/ollama/blood")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("ok", "degraded", "unavailable")
    assert "ollama_blood" in data or "cognitive_blood_active" in data or "blood_pressure_score" in data


def test_react_dashboard_endpoint_read_only():
    """GET /api/ui/react-dashboard debe ser read-only."""
    resp = client.get("/api/ui/react-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert data.get("policy", {}).get("read_only") is True
    assert data.get("policy", {}).get("identity_core_protected") is True
    assert data.get("policy", {}).get("no_shell_execution") is True


def test_react_dashboard_contains_heartbeat():
    """El dashboard debe incluir heartbeat."""
    resp = client.get("/api/ui/react-dashboard")
    data = resp.json()
    assert "heartbeat" in data
    assert "runtime_enabled" in data["heartbeat"] or "mode" in data["heartbeat"]


def test_react_dashboard_contains_ollama_blood():
    """El dashboard debe incluir ollama_blood."""
    resp = client.get("/api/ui/react-dashboard")
    data = resp.json()
    assert "ollama_blood" in data
    assert "cognitive_blood_active" in data["ollama_blood"]


def test_react_dashboard_contains_repo_status():
    """El dashboard debe incluir git_status."""
    resp = client.get("/api/ui/react-dashboard")
    data = resp.json()
    assert "git_status" in data
    assert "branch" in data["git_status"]


def test_technical_debt_endpoint():
    """GET /api/system/technical-debt debe responder con auditoría."""
    resp = client.get("/api/system/technical-debt")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") == "ok"
    assert "score" in data
    assert "debts" in data
    assert "warnings" in data
    assert "recommended_actions" in data


def test_identity_core_not_modified_by_ui_dashboard():
    """Los endpoints de dashboard no deben modificar identity_core."""
    resp_debt = client.get("/api/system/technical-debt")
    resp_dash = client.get("/api/ui/react-dashboard")
    assert resp_debt.status_code == 200
    assert resp_dash.status_code == 200
    assert resp_dash.json().get("policy", {}).get("identity_core_protected") is True


def test_ollama_blood_alias_routes():
    """Los alias de Ollama Blood deben responder."""
    resp1 = client.get("/api/models/ollama/blood")
    resp2 = client.get("/api/system/ollama-blood")
    resp3 = client.get("/api/runtime/blood")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp3.status_code == 200


def test_repo_runtime_status_no_shell_user_input():
    """repo_runtime_status no debe aceptar input de usuario ni ejecutar shell arbitrario."""
    status = build_repo_runtime_status()
    assert isinstance(status, dict)
    assert "status" in status
    assert status["status"] in ("ok", "unavailable")
    assert "dirty" in status or "error" in status
    assert "branch" in status or "error" in status
    assert "commit" in status or "error" in status


def test_spa_routes_return_html_or_index():
    """Las rutas SPA deben devolver HTML."""
    for route in ["/", "/ui", "/observabilidad", "/ui/observabilidad"]:
        resp = client.get(route)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")


def test_react_dashboard_has_generated_at():
    """El dashboard debe incluir generated_at y refresh_hint_seconds."""
    resp = client.get("/api/ui/react-dashboard")
    data = resp.json()
    assert "generated_at" in data
    assert "refresh_hint_seconds" in data
