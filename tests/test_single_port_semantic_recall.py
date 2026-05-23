"""Tests de activación del recall y gobierno semántico desde la API 1.9D/1.9E."""

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
                "authorized_matches_count": 1,
                "governance": {"allowed_vector_matches": 1},
            },
        }


class FakeGovernance:
    def doctor(self):
        return {
            "status": "ok",
            "mode": "semantic-memory-governance-1.9E",
            "policy": {"default_allowed_statuses": ["stable"]},
        }

    def transition_document(self, document_id: str, **kwargs):
        return {
            "status": "ok",
            "document_id": document_id,
            "previous_status": "candidate",
            "new_status": kwargs["new_status"],
            "reason": kwargs["reason"],
            "approved_by": kwargs["approved_by"],
        }


def test_api_run_passes_semantic_governance_configuration_to_runner() -> None:
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
                "semantic_allow_experimental": True,
                "context": {"project_id": "triade-local"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["semantic_recall"]["authorized_matches_count"] == 1
    assert FakeRunner.captured_run["semantic_recall_enabled"] is True
    assert FakeRunner.captured_run["semantic_model"] == "nomic-embed-text:latest"
    assert FakeRunner.captured_run["semantic_limit"] == 2
    assert FakeRunner.captured_run["semantic_min_similarity"] == 0.6
    assert FakeRunner.captured_run["semantic_domain"] == "crystal"
    assert FakeRunner.captured_run["semantic_allow_experimental"] is True


def test_governance_doctor_endpoint_exposes_policy() -> None:
    with patch("apps.single_port_app.SemanticMemoryGovernance", return_value=FakeGovernance()):
        response = client.get("/api/semantic/governance/doctor")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "semantic-memory-governance-1.9E"
    assert payload["policy"]["default_allowed_statuses"] == ["stable"]


def test_transition_endpoint_promotes_document_with_evidence() -> None:
    with patch("apps.single_port_app.SemanticMemoryGovernance", return_value=FakeGovernance()):
        response = client.post(
            "/api/semantic/documents/sem-crystal/transition",
            json={
                "new_status": "experimental",
                "reason": "Documento validado durante prueba 1.9E.",
                "approved_by": "santiago",
                "evidence": {"phase": "1.9E"},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == "sem-crystal"
    assert payload["new_status"] == "experimental"
    assert payload["approved_by"] == "santiago"
