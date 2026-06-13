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
    assert data.get("status") in ("ok", "partial")
    assert data.get("policy", {}).get("read_only") is True
    assert data.get("policy", {}).get("identity_core_protected") is True
    assert data.get("policy", {}).get("no_shell_execution") is True


def test_react_dashboard_errors_array():
    """El dashboard debe incluir un array errors (puede estar vacío)."""
    resp = client.get("/api/ui/react-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "errors" in data
    assert isinstance(data["errors"], list)
    for err in data["errors"]:
        assert "block" in err
        assert "error" in err


def test_react_dashboard_partial_not_500():
    """Si un bloque falla, status es 'partial' y no 500."""
    resp = client.get("/api/ui/react-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("ok", "partial")
    if data.get("errors"):
        # al menos un bloque falló — asegurarse que los demás bloques existen
        assert "heartbeat" in data
        assert "ollama_blood" in data
        assert "git_status" in data


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


def test_react_dashboard_contains_system_processes():
    """El dashboard debe incluir system_processes con estado de runtime."""
    resp = client.get("/api/ui/react-dashboard")
    data = resp.json()
    assert "system_processes" in data
    sp = data["system_processes"]
    for k in ("runtime_enabled", "runtime_mode", "background_thread_alive", "workers_active", "active_tasks", "cycles_last_hour", "latest_action"):
        assert k in sp, f"Missing system_processes.{k}"


def test_repo_runtime_status_uses_whitelist_no_shell():
    """build_repo_runtime_status usa solo comandos whitelist con shell=False."""
    import inspect
    from triade.core.repo_runtime_status import build_repo_runtime_status, _run_git
    src = inspect.getsource(_run_git)
    assert "shell=False" in src, "_run_git debe usar shell=False"
    assert "subprocess.run" in src
    assert '["git"]' in src or '"git"' in src
    status = build_repo_runtime_status()
    assert status.get("status") in ("ok", "unavailable")


def test_react_dashboard_contains_technical_debt():
    """El dashboard debe incluir technical_debt con score."""
    resp = client.get("/api/ui/react-dashboard")
    data = resp.json()
    assert "technical_debt" in data
    assert "score" in data["technical_debt"]


def test_runtime_once_records_cycle_event():
    """POST /api/runtime/once debe registrar runtime_cycle_start / complete."""
    resp = client.post("/api/runtime/once", json={"mode": "observe_only"})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("ok", "error")
    if data.get("status") == "ok":
        assert data.get("cycle_recorded") is True
        assert data.get("cycle_id")
        assert data.get("mode") == "observe_only"
        # Verificar que se publicaron eventos de ciclo
        events_resp = client.get("/api/runtime/events?limit=10")
        ev = events_resp.json()
        types = {e.get("event_type") for e in ev.get("events", [])}
        assert types & {"runtime_cycle_start", "runtime_cycle_started"}, "Falta runtime_cycle_start/started"
        assert types & {"runtime_cycle_complete", "runtime_cycle_completed"}, "Falta runtime_cycle_complete/completed"


def test_heartbeat_contains_api_server_alive():
    """GET /api/runtime/heartbeat debe incluir api_server_alive y heartbeat_truth."""
    resp = client.get("/api/runtime/heartbeat")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("api_server_alive") is True
    assert data.get("heartbeat_truth") in (
        "API encendida, runtime apagado",
        "Runtime activo sin ciclos recientes",
        "Runtime activo con ciclos recientes",
    )


def test_heartbeat_counts_both_event_variants():
    """build_runtime_heartbeat cuenta runtime_cycle_start y runtime_cycle_started."""
    from triade.core.internal_runtime import RUNTIME_CYCLE_EVENTS
    assert "runtime_cycle_start" in RUNTIME_CYCLE_EVENTS
    assert "runtime_cycle_started" in RUNTIME_CYCLE_EVENTS
    assert "runtime_cycle_complete" in RUNTIME_CYCLE_EVENTS
    assert "runtime_cycle_completed" in RUNTIME_CYCLE_EVENTS


def test_heartbeat_truth_api_alive_runtime_off():
    """Cuando runtime está apagado, heartbeat_truth lo indica."""
    from triade.core.internal_runtime import stop_internal_runtime_background
    stop_internal_runtime_background()
    resp = client.get("/api/runtime/heartbeat")
    data = resp.json()
    assert data.get("api_server_alive") is True
    if not data.get("runtime_enabled"):
        assert data.get("heartbeat_truth") == "API encendida, runtime apagado"


def test_runtime_start_reports_background_thread():
    """POST /api/runtime/start debe devolver background_thread_alive."""
    from triade.core.internal_runtime import stop_internal_runtime_background
    stop_internal_runtime_background()
    # Usar interval muy largo para que no se ejecuten ciclos
    resp = client.post("/api/runtime/start", json={"mode": "observe_only", "interval_seconds": 9999})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in ("started", "already_running")
    assert data.get("mode") == "observe_only"
    assert "background_thread_alive" in data
    # Limpiar
    stop_internal_runtime_background()


def test_react_dashboard_shows_runtime_off_not_error():
    """Cuando runtime está apagado, el dashboard no debe mostrar error."""
    from triade.core.internal_runtime import stop_internal_runtime_background
    stop_internal_runtime_background()
    resp = client.get("/api/ui/react-dashboard")
    assert resp.status_code == 200
    data = resp.json()
    hb = data.get("heartbeat", {})
    assert hb.get("api_server_alive") is True
    assert "runtime_enabled" in hb
    if not hb.get("runtime_enabled"):
        assert "heartbeat_truth" in hb
        assert hb["heartbeat_truth"] == "API encendida, runtime apagado"
    # No debe ser error
    assert data.get("status") in ("ok", "partial")
