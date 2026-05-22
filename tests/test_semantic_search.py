"""Tests de búsqueda por similitud semántica 1.9C."""

from __future__ import annotations

import math

import pytest

from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_search import SemanticSearchEngine
from triade.memory.semantic_store import SemanticMemoryStore
from triade.models.ollama_client import EmbeddingResult


MIGRATION = "triade/memory/migrations/001_9A_semantic_memory.sql"
MODEL = "nomic-embed-text:latest"


class FakeSearchClient:
    def __init__(self, query_vector: list[float] | None = None) -> None:
        self.query_vector = query_vector or [1.0, 0.0, 0.0]

    def health(self) -> dict[str, object]:
        return {"ok": True, "models": [MODEL], "base_url": "fake://ollama"}

    def embed(self, model: str, input_text: str, truncate: bool = True, dimensions: int | None = None) -> EmbeddingResult:
        return EmbeddingResult(ok=True, model=model, embeddings=[self.query_vector])


def build_engine(tmp_path, query_vector: list[float] | None = None) -> tuple[SemanticSearchEngine, SemanticMemoryStore]:
    store = SemanticMemoryStore(db_path=tmp_path / "semantic.db", migration_path=MIGRATION)
    client = FakeSearchClient(query_vector=query_vector)
    embed_engine = SemanticEmbeddingEngine(store=store, client=client)
    return SemanticSearchEngine(store=store, client=client, embedding_engine=embed_engine), store


def add_document(store: SemanticMemoryStore, content: str, vector: list[float], domain: str = "general", model: str = MODEL) -> str:
    document = store.upsert_document(content, domain=domain, source_type="test")
    store.store_embedding(document.document_id, model, vector)
    return document.document_id


def test_cosine_similarity_calculates_expected_values() -> None:
    assert SemanticSearchEngine.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert SemanticSearchEngine.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert SemanticSearchEngine.cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_search_ranks_documents_by_cosine_similarity(tmp_path) -> None:
    engine, store = build_engine(tmp_path)
    closest = add_document(store, "Cristal y continuidad", [1.0, 0.0, 0.0], domain="crystal")
    medium = add_document(store, "Memoria relacionada", [0.8, 0.2, 0.0], domain="memory")
    far = add_document(store, "Tema distante", [0.0, 1.0, 0.0], domain="general")

    result = engine.search("regulación de continuidad", model=MODEL, limit=3)

    assert result["status"] == "ok"
    assert [item["document_id"] for item in result["results"]] == [closest, medium, far]
    assert result["results"][0]["similarity"] == pytest.approx(1.0)
    assert result["results"][1]["similarity"] > result["results"][2]["similarity"]


def test_search_filters_domain_and_min_similarity(tmp_path) -> None:
    engine, store = build_engine(tmp_path)
    add_document(store, "Documento Crystal", [1.0, 0.0, 0.0], domain="crystal")
    add_document(store, "Documento Memory cercano", [0.95, 0.05, 0.0], domain="memory")
    add_document(store, "Documento Memory distante", [0.0, 1.0, 0.0], domain="memory")

    result = engine.search("consulta", model=MODEL, domain="memory", min_similarity=0.9)

    assert result["status"] == "ok"
    assert len(result["results"]) == 1
    assert result["results"][0]["domain"] == "memory"
    assert "cercano" in result["results"][0]["content"]


def test_search_skips_incompatible_models_and_dimensions(tmp_path) -> None:
    engine, store = build_engine(tmp_path)
    add_document(store, "Compatible", [1.0, 0.0, 0.0], model=MODEL)
    add_document(store, "Otro modelo", [1.0, 0.0, 0.0], model="qwen3-embedding:0.6b")
    add_document(store, "Otra dimensión", [1.0, 0.0], model=MODEL)

    result = engine.search("consulta", model=MODEL)

    assert result["status"] == "ok"
    assert len(result["results"]) == 1
    assert result["skipped_model"] == 1
    assert result["skipped_dimensions"] == 1


def test_search_validates_query_and_limits(tmp_path) -> None:
    engine, _ = build_engine(tmp_path)

    assert engine.search("   ")["status"] == "failed"
    assert engine.search("consulta", limit=0)["status"] == "failed"
    assert engine.search("consulta", min_similarity=2.0)["status"] == "failed"


def test_search_rejects_zero_or_different_vectors() -> None:
    with pytest.raises(ValueError):
        SemanticSearchEngine.cosine_similarity([], [])
    with pytest.raises(ValueError):
        SemanticSearchEngine.cosine_similarity([1.0], [1.0, 0.0])
    with pytest.raises(ValueError):
        SemanticSearchEngine.cosine_similarity([0.0, 0.0], [1.0, 0.0])
