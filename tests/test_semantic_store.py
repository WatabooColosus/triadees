"""Tests del almacenamiento semántico persistente 1.9A."""

from __future__ import annotations

import math

import pytest

from triade.memory.semantic_store import SemanticMemoryStore


MIGRATION = "triade/memory/migrations/001_9A_semantic_memory.sql"


def store(tmp_path) -> SemanticMemoryStore:
    return SemanticMemoryStore(db_path=tmp_path / "semantic.db", migration_path=MIGRATION)


def test_semantic_store_initializes_tables(tmp_path) -> None:
    memory = store(tmp_path)
    with memory._connect() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    assert "semantic_documents" in tables
    assert "semantic_embeddings" in tables


def test_upsert_document_normalizes_and_persists_metadata(tmp_path) -> None:
    memory = store(tmp_path)
    document = memory.upsert_document(
        content="  El Cristal   regula   continuidad temporal.  ",
        domain="crystal",
        source_type="manual",
        source_ref="test",
        metadata={"phase": "1.9A"},
    )
    persisted = memory.get_document(document.document_id)

    assert document.normalized_content == "El Cristal regula continuidad temporal."
    assert persisted is not None
    assert persisted["domain"] == "crystal"
    assert persisted["metadata"]["phase"] == "1.9A"


def test_upsert_document_deduplicates_same_normalized_content(tmp_path) -> None:
    memory = store(tmp_path)
    first = memory.upsert_document("Memoria semántica real")
    second = memory.upsert_document("  Memoria   semántica real  ")

    assert first.document_id == second.document_id
    assert len(memory.list_documents()) == 1


def test_store_embedding_validates_and_persists_vector(tmp_path) -> None:
    memory = store(tmp_path)
    document = memory.upsert_document("Documento para vector", domain="memory")
    embedding = memory.store_embedding(document.document_id, "test-embedding", [0.3, 0.4])
    rows = memory.list_embeddings(document.document_id)

    assert embedding.dimensions == 2
    assert math.isclose(embedding.vector_norm, 0.5)
    assert rows[0]["embedding_model"] == "test-embedding"
    assert rows[0]["vector"] == [0.3, 0.4]


def test_embedding_requires_existing_document_and_nonzero_vector(tmp_path) -> None:
    memory = store(tmp_path)
    document = memory.upsert_document("Documento válido")

    with pytest.raises(KeyError):
        memory.store_embedding("missing", "test-model", [1.0])
    with pytest.raises(ValueError):
        memory.store_embedding(document.document_id, "test-model", [0.0, 0.0])


def test_semantic_doctor_reports_pending_embedding_generation(tmp_path) -> None:
    memory = store(tmp_path)
    document = memory.upsert_document("Sin vector todavía")
    before = memory.doctor()
    memory.store_embedding(document.document_id, "test-model", [1.0, 0.0])
    after = memory.doctor()

    assert before["documents"] == 1
    assert before["documents_without_embedding"] == 1
    assert before["embedding_generation"] == "pending_1.9B"
    assert after["embeddings"] == 1
    assert after["documents_without_embedding"] == 0
