"""Tests de activación del recall semántico desde la API Single Port 1.9D."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.single_port_app import app


client = TestClient(app)


class FakeRunner:
    captured_init = None
    captured_run = None

    def __init__(self, **kwargs):
        FakeRunner.captured_init = kwargs

    def run(self, text: str, **kwargs):
        FakeRunner.captured_run = {"text": text, **kwargs}
        return {
            "run_id": "run-semantic-recall",
            "response": "Respuesta de prueba.",
            "semantic_recall": {
                "enabled": True,
                "status": "ok",
                "model": "nomic-embed-text:latest",
                "matches_count": 1,
                "matches": [{"document_id": "sem-crystal", "retrieval_type": "vector_similarity"}],
            },
        }


def test_api_run_passes_semantic_recall_configuration_to_runner() -> None:
    with patch("apps.single_port_app.TriadeRunner", FakeRunner):
        response = client.post(
            "/api/run",
            json={
                "text": "Qué órgano regula continuidad",
                "source": "api-test",
                "use_ollama": False,
                "semantic_recall_enabled": True,
                "semantic_model": "nomic-embed-text:latest",
                "semantic_limit": 2,
                "semantic_min_similarity": 0.6,
                "semantic_domain": "crystal",
                "context": {"project_id": "triade-local"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["semantic_recall"]["matches_count"] == 1
    assert FakeRunner.captured_run["semantic_recall_enabled"] is True
    assert FakeRunner.captured_run["semantic_model"] == "nomic-embed-text:latest"
    assert FakeRunner.captured_run["semantic_limit"] == 2
    assert FakeRunner.captured_run["semantic_min_similarity"] == 0.6
    assert FakeRunner.captured_run["semantic_domain"] == "crystal"
