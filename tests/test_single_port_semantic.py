"""Tests de endpoints semánticos de la Single Port App 1.9B."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.single_port_app import app


client = TestClient(app)


class FakeSemanticEngine:
    def doctor(self):
        return {
            "status": "ok",
            "mode": "semantic-embedding-engine-1.9B",
            "selection": {"ok": True, "selected_model": "nomic-embed-text:latest"},
        }

    def ingest_and_embed(self, **kwargs):
        return {
            "document": {"document_id": "sem-test", "content": kwargs["content"]},
            "embedding_event": {
                "ok": True,
                "document_id": "sem-test",
                "model": kwargs.get("model") or "nomic-embed-text:latest",
                "dimensions": 3,
                "status": "stored",
            },
        }

    def embed_document(self, document_id: str, model: str | None = None):
        class Event:
            def to_dict(self):
                return {
                    "ok": True,
                    "document_id": document_id,
                    "model": model or "nomic-embed-text:latest",
                    "dimensions": 3,
                    "status": "stored",
                }
        return Event()


def test_semantic_doctor_endpoint_exposes_engine_status() -> None:
    with patch("apps.single_port_app.SemanticEmbeddingEngine", return_value=FakeSemanticEngine()):
        response = client.get("/api/semantic/doctor")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "semantic-embedding-engine-1.9B"
    assert payload["selection"]["selected_model"] == "nomic-embed-text:latest"


def test_ingest_and_embed_endpoint_accepts_document_payload() -> None:
    with patch("apps.single_port_app.SemanticEmbeddingEngine", return_value=FakeSemanticEngine()):
        response = client.post(
            "/api/semantic/ingest-and-embed",
            json={
                "content": "La memoria semántica conecta significados.",
                "domain": "memory",
                "source_ref": "test-api",
                "model": "nomic-embed-text:latest",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document"]["document_id"] == "sem-test"
    assert payload["embedding_event"]["ok"] is True
    assert payload["embedding_event"]["model"] == "nomic-embed-text:latest"


def test_embed_existing_document_endpoint_accepts_model() -> None:
    with patch("apps.single_port_app.SemanticEmbeddingEngine", return_value=FakeSemanticEngine()):
        response = client.post(
            "/api/semantic/documents/sem-existing/embed",
            json={"model": "qwen3-embedding:0.6b"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == "sem-existing"
    assert payload["model"] == "qwen3-embedding:0.6b"
    assert payload["status"] == "stored"
