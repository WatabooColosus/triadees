"""Tests de exposición de contexto del Cristal por la Single Port App 1.8F."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.single_port_app import app


client = TestClient(app)


def test_single_port_run_accepts_crystal_context() -> None:
    response = client.post(
        "/api/run",
        json={
            "text": "Prueba contextual desde API",
            "source": "api-test-context",
            "use_ollama": False,
            "context": {
                "project_id": "triade-pruebas",
                "active_neuron": "cristal",
                "context_scope": "project_neuron",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    temporal = payload["crystal_temporal_state"]
    assert temporal["context_scope"] == "project_neuron"
    assert "project_id=triade-pruebas" in temporal["context_key"]
    assert "active_neuron=cristal" in temporal["context_key"]
    assert temporal["comparison_basis"]["project_id"] == "triade-pruebas"
