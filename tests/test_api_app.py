"""Pruebas de la API local FastAPI de Tríade Ω."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from apps.single_port_app import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["entity"] == "Tríade Ω"
    assert "doctor" in payload
    assert "security" in payload


def test_identity_verify_endpoint(tmp_path) -> None:
    response = client.get(
        "/api/identity/verify", params={"db_path": str(tmp_path / "identity.db")}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["identity"] == "Triade Omega"
    assert payload["integrity"] == "verified"
    assert payload["tamper_detected"] is False


def test_triade_run_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TRIADE_API_KEY", raising=False)
    response = client.post(
        "/triade/run",
        json={
            "text": "Run desde API test",
            "source": "test-api",
            "runs_dir": str(tmp_path / "runs"),
            "db_path": str(tmp_path / "triade.db"),
            "use_ollama": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"].startswith("run-")
    assert payload["memory_diff"]["stored"] is True
    assert payload["models"]["central"]["provider"] == "template"


def test_triade_recall_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("TRIADE_API_KEY", raising=False)
    response = client.get("/triade/recall", params={"query": "", "limit": 3})
    assert response.status_code == 200
    payload = response.json()
    assert "episodes" in payload
    assert "count" in payload


def test_triade_doctor_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("TRIADE_API_KEY", raising=False)
    response = client.get("/triade/doctor", params={"use_ollama": False})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "counts" in payload


def test_api_key_blocks_sensitive_endpoints(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRIADE_API_KEY", "test-secret")
    response = client.post(
        "/triade/run",
        json={
            "text": "Debe bloquear sin API key",
            "runs_dir": str(tmp_path / "runs"),
            "db_path": str(tmp_path / "triade.db"),
            "use_ollama": False,
        },
    )
    assert response.status_code == 401


def test_api_key_allows_sensitive_endpoints(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRIADE_API_KEY", "test-secret")
    response = client.post(
        "/triade/run",
        headers={"X-TRIADE-API-Key": "test-secret"},
        json={
            "text": "Debe permitir con API key",
            "runs_dir": str(tmp_path / "runs"),
            "db_path": str(tmp_path / "triade.db"),
            "use_ollama": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["memory_diff"]["stored"] is True


def test_single_port_app_exposes_observability_and_ui() -> None:
    obs = client.get("/api/observability?limit=2")
    assert obs.status_code == 200
    assert obs.json()["mode"] == "triade_observability_view"

    ui = client.get("/observabilidad")
    assert ui.status_code == 200


def test_governance_registers_existing_neuron_specification(tmp_path, monkeypatch) -> None:
    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE neurons (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, mission TEXT NOT NULL,
                domain TEXT, inputs_allowed TEXT, outputs_allowed TEXT,
                created_by TEXT)"""
        )
        conn.execute(
            """INSERT INTO neurons VALUES
            (1,'Central','coordinar','coordination','["signal"]','["proposal"]','bootstrap')"""
        )
    monkeypatch.setenv("TRIADE_DB_PATH", str(db))
    monkeypatch.setenv("TRIADE_API_KEY", "test-secret")

    response = client.post(
        "/api/governance/neurons/1/specification",
        headers={"X-TRIADE-API-Key": "test-secret"},
        json={
            "version": "1.0.0",
            "component": "triade.neurons.central",
            "provides_capabilities": ["learning_coordination"],
            "max_memory_mb": 512,
            "max_runtime_seconds": 60,
            "max_storage_mb": 128,
            "approved_by": "human-reviewer",
        },
    )

    assert response.status_code == 200
    assert response.json()["specification"]["state"] == "specified"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM neuron_specifications").fetchone()[0] == 1


def test_cabina_runtime_mutations_require_its_api_key(monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_API_KEY", "cabin-secret")

    for endpoint in (
        "/api/runtime/once",
        "/api/runtime/start",
        "/api/runtime/stop",
        "/api/runtime/workers/once",
    ):
        response = client.post(endpoint, json={})
        assert response.status_code == 401, endpoint


def test_governed_peft_signature_uses_canonical_version_id(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TRIADE_DB_PATH", str(tmp_path / "triade.db"))
    monkeypatch.setenv("TRIADE_API_KEY", "cabin-secret")

    denied = client.post(
        "/api/governance/peft/governed/activate",
        json={"version_id": "missing", "approved_by": "reviewer"},
    )
    assert denied.status_code == 401

    response = client.post(
        "/api/governance/peft/governed/activate",
        headers={"X-TRIADE-API-Key": "cabin-secret"},
        json={"version_id": "missing", "approved_by": "reviewer"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "blocked",
        "reason": "passing_canary_required",
    }


def test_governed_remediation_routes_require_api_key(monkeypatch) -> None:
    monkeypatch.setenv("TRIADE_API_KEY", "cabin-secret")
    payloads = {
        "/api/governance/peft/governed/retire-incompatible": {
            "version_id": "missing",
            "approved_by": "Santiago",
        },
        "/api/governance/improvement/proposals/missing/target": {
            "neuron_id": "1",
            "version": "1.0.0",
            "assigned_by": "Santiago",
        },
    }
    for endpoint, payload in payloads.items():
        assert client.post(endpoint, json=payload).status_code == 401
