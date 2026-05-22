"""Motor de embeddings locales para memoria semántica · Tríade Ω 1.9B.

Conecta OllamaClient.embed con SemanticMemoryStore. Esta fase genera y guarda
vectores reales, pero todavía no modifica el recall del Runner.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from triade.models.ollama_client import EmbeddingResult, OllamaClient

from .semantic_store import SemanticMemoryStore


@dataclass(slots=True)
class SemanticEmbeddingEvent:
    ok: bool
    document_id: str
    model: str | None
    dimensions: int = 0
    status: str = "failed"
    error: str | None = None
    provider: str = "ollama"
    embedding_id_stored: bool = False
    model_selection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SemanticEmbeddingEngine:
    """Vectoriza documentos semánticos utilizando modelos locales instalados."""

    PREFERRED_MODELS = [
        "nomic-embed-text:latest",
        "qwen3-embedding:0.6b",
        "nomic-embed-text",
    ]

    def __init__(
        self,
        store: SemanticMemoryStore | None = None,
        client: OllamaClient | None = None,
        preferred_models: list[str] | None = None,
    ) -> None:
        self.store = store or SemanticMemoryStore()
        self.client = client or OllamaClient()
        self.preferred_models = preferred_models or list(self.PREFERRED_MODELS)

    def select_model(self, requested_model: str | None = None) -> dict[str, Any]:
        health = self.client.health()
        available = [str(model) for model in health.get("models", []) if model]
        if not health.get("ok"):
            return {
                "ok": False,
                "selected_model": None,
                "available_models": available,
                "reason": "ollama_unavailable",
                "error": health.get("error"),
            }
        if requested_model:
            if requested_model in available:
                return {
                    "ok": True,
                    "selected_model": requested_model,
                    "available_models": available,
                    "reason": "requested_model_available",
                    "error": None,
                }
            return {
                "ok": False,
                "selected_model": None,
                "available_models": available,
                "reason": "requested_model_not_installed",
                "error": f"Modelo no instalado en Ollama: {requested_model}",
            }
        for model in self.preferred_models:
            if model in available:
                return {
                    "ok": True,
                    "selected_model": model,
                    "available_models": available,
                    "reason": "preferred_installed_embedding_model",
                    "error": None,
                }
        return {
            "ok": False,
            "selected_model": None,
            "available_models": available,
            "reason": "no_embedding_model_installed",
            "error": "No se encontró un modelo de embeddings local permitido.",
        }

    def embed_document(self, document_id: str, model: str | None = None) -> SemanticEmbeddingEvent:
        document = self.store.get_document(document_id)
        if document is None:
            return SemanticEmbeddingEvent(
                ok=False,
                document_id=document_id,
                model=model,
                error=f"No existe documento semántico: {document_id}",
                model_selection_reason="document_not_found",
            )
        selection = self.select_model(requested_model=model)
        selected_model = selection.get("selected_model")
        if not selection.get("ok") or not selected_model:
            return SemanticEmbeddingEvent(
                ok=False,
                document_id=document_id,
                model=model,
                error=selection.get("error"),
                model_selection_reason=str(selection.get("reason", "selection_failed")),
            )
        result: EmbeddingResult = self.client.embed(
            str(selected_model),
            str(document["normalized_content"]),
        )
        if not result.ok or not result.embeddings:
            return SemanticEmbeddingEvent(
                ok=False,
                document_id=document_id,
                model=str(selected_model),
                error=result.error or "Ollama no produjo vector.",
                model_selection_reason=str(selection["reason"]),
            )
        stored = self.store.store_embedding(
            document_id=document_id,
            embedding_model=str(selected_model),
            vector=result.embeddings[0],
            status="stored",
        )
        return SemanticEmbeddingEvent(
            ok=True,
            document_id=document_id,
            model=str(selected_model),
            dimensions=stored.dimensions,
            status="stored",
            embedding_id_stored=True,
            model_selection_reason=str(selection["reason"]),
        )

    def ingest_and_embed(
        self,
        content: str,
        domain: str = "general",
        source_type: str = "manual",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        document = self.store.upsert_document(
            content=content,
            domain=domain,
            source_type=source_type,
            source_ref=source_ref,
            metadata=metadata,
            status="candidate",
        )
        event = self.embed_document(document.document_id, model=model)
        return {"document": document.to_dict(), "embedding_event": event.to_dict()}

    def embed_pending(self, limit: int = 20, model: str | None = None) -> dict[str, Any]:
        documents = self.store.list_documents(limit=limit)
        embedded = {item["document_id"] for item in self.store.list_embeddings()}
        pending = [document for document in documents if document["document_id"] not in embedded]
        events = [self.embed_document(document["document_id"], model=model).to_dict() for document in pending]
        return {
            "status": "ok",
            "requested_limit": limit,
            "pending_found": len(pending),
            "embedded_ok": sum(1 for event in events if event["ok"]),
            "events": events,
        }

    def doctor(self) -> dict[str, Any]:
        selection = self.select_model()
        return {
            "status": "ok" if selection.get("ok") else "warning",
            "mode": "semantic-embedding-engine-1.9B",
            "selection": selection,
            "store": self.store.doctor(),
            "runner_integration": "pending_1.9D",
            "semantic_search": "pending_1.9C",
        }
