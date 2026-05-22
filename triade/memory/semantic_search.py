"""Búsqueda por similitud semántica · Tríade Ω 1.9C.

Vectoriza una consulta con el mismo modelo usado para documentos persistidos y
calcula similitud coseno. Esta fase expone ranking verificable, pero todavía no
inyecta resultados automáticamente al ciclo cognitivo del Runner.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from triade.models.ollama_client import OllamaClient

from .semantic_embedding_engine import SemanticEmbeddingEngine
from .semantic_store import SemanticMemoryStore


@dataclass(slots=True)
class SemanticMatch:
    document_id: str
    similarity: float
    embedding_model: str
    dimensions: int
    domain: str
    content: str
    source_type: str
    source_ref: str | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticSearchEngine:
    """Busca documentos cercanos a una consulta mediante similitud coseno."""

    def __init__(
        self,
        store: SemanticMemoryStore | None = None,
        client: OllamaClient | None = None,
        embedding_engine: SemanticEmbeddingEngine | None = None,
    ) -> None:
        self.store = store or SemanticMemoryStore()
        self.client = client or OllamaClient()
        self.embedding_engine = embedding_engine or SemanticEmbeddingEngine(store=self.store, client=self.client)

    def search(
        self,
        query: str,
        model: str | None = None,
        limit: int = 5,
        min_similarity: float = -1.0,
        domain: str | None = None,
    ) -> dict[str, Any]:
        normalized_query = self.store.normalize_content(query)
        if not normalized_query:
            return {"status": "failed", "error": "La consulta semántica no puede estar vacía.", "results": []}
        if limit < 1 or limit > 50:
            return {"status": "failed", "error": "limit debe estar entre 1 y 50.", "results": []}
        if min_similarity < -1.0 or min_similarity > 1.0:
            return {"status": "failed", "error": "min_similarity debe estar entre -1 y 1.", "results": []}

        selection = self.embedding_engine.select_model(requested_model=model)
        selected_model = selection.get("selected_model")
        if not selection.get("ok") or not selected_model:
            return {
                "status": "failed",
                "error": selection.get("error"),
                "model_selection": selection,
                "results": [],
            }

        query_result = self.client.embed(str(selected_model), normalized_query)
        if not query_result.ok or not query_result.embeddings:
            return {
                "status": "failed",
                "error": query_result.error or "No se pudo vectorizar la consulta.",
                "model": selected_model,
                "results": [],
            }
        query_vector = query_result.embeddings[0]
        candidates = self.store.list_embeddings()
        matches: list[SemanticMatch] = []
        skipped_model = 0
        skipped_dimensions = 0
        skipped_missing_document = 0

        for embedding in candidates:
            if embedding.get("embedding_model") != selected_model:
                skipped_model += 1
                continue
            vector = embedding.get("vector", [])
            if len(vector) != len(query_vector):
                skipped_dimensions += 1
                continue
            document = self.store.get_document(str(embedding["document_id"]))
            if not document:
                skipped_missing_document += 1
                continue
            if domain and document.get("domain") != domain:
                continue
            similarity = self.cosine_similarity(query_vector, vector)
            if similarity < min_similarity:
                continue
            matches.append(
                SemanticMatch(
                    document_id=str(document["document_id"]),
                    similarity=round(similarity, 6),
                    embedding_model=str(selected_model),
                    dimensions=len(vector),
                    domain=str(document.get("domain") or "general"),
                    content=str(document.get("content") or ""),
                    source_type=str(document.get("source_type") or "manual"),
                    source_ref=document.get("source_ref"),
                    metadata=dict(document.get("metadata") or {}),
                )
            )

        matches.sort(key=lambda item: item.similarity, reverse=True)
        ranked = matches[:limit]
        return {
            "status": "ok",
            "mode": "semantic-similarity-search-1.9C",
            "query": normalized_query,
            "model": selected_model,
            "query_dimensions": len(query_vector),
            "candidate_embeddings": len(candidates),
            "matching_candidates": len(matches),
            "skipped_model": skipped_model,
            "skipped_dimensions": skipped_dimensions,
            "skipped_missing_document": skipped_missing_document,
            "limit": limit,
            "min_similarity": min_similarity,
            "domain": domain,
            "results": [item.to_dict() for item in ranked],
            "runner_integration": "pending_1.9D",
        }

    @staticmethod
    def cosine_similarity(left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            raise ValueError("Los vectores deben tener la misma dimensión y no estar vacíos.")
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm <= 0 or right_norm <= 0:
            raise ValueError("Los vectores no pueden tener norma cero.")
        return dot / (left_norm * right_norm)
