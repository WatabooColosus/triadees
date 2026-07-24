"""Motor de embeddings locales para memoria semántica · Tríade Ω 1.9B.

Conecta OllamaClient.embed con SemanticMemoryStore. Soporta fallback local
con sentence-transformers cuando Ollama no está disponible.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from triade.models.ollama_client import EmbeddingResult, OllamaClient

from .semantic_store import SemanticMemoryStore

logger = logging.getLogger(__name__)


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


class LocalEmbeddingProvider:
    """Proveedor de embeddings local usando sentence-transformers."""

    DEFAULT_MODEL = "all-MiniLM-L6-v2"

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _load_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
                logger.info("Modelo de embedding local cargado: %s", self.model_name)
            except Exception as exc:
                logger.error("Error cargando modelo de embedding local: %s", exc)
                raise
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._load_model()
        embedding = model.encode(text, show_progress_bar=False)
        return embedding.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        embeddings = model.encode(texts, show_progress_bar=False)
        return embeddings.tolist()

    @property
    def dimensions(self) -> int:
        model = self._load_model()
        return model.get_sentence_embedding_dimension()


class SemanticEmbeddingEngine:
    """Vectoriza documentos semánticos utilizando modelos locales instalados."""

    PREFERRED_MODELS = [
        "nomic-embed-text:latest",
        "qwen3-embedding:0.6b",
        "nomic-embed-text",
    ]

    LOCAL_MODEL_NAME = "local-sentence-transformers"

    def __init__(
        self,
        store: SemanticMemoryStore | None = None,
        client: OllamaClient | None = None,
        preferred_models: list[str] | None = None,
        use_local_fallback: bool = True,
    ) -> None:
        self.store = store or SemanticMemoryStore()
        self.client = client or OllamaClient()
        self.preferred_models = preferred_models or list(self.PREFERRED_MODELS)
        self.use_local_fallback = use_local_fallback
        self._local_provider: LocalEmbeddingProvider | None = None

    def _get_local_provider(self) -> LocalEmbeddingProvider | None:
        if not self.use_local_fallback:
            return None
        if self._local_provider is None:
            try:
                self._local_provider = LocalEmbeddingProvider()
            except Exception as exc:
                logger.warning("No se pudo inicializar proveedor local: %s", exc)
                return None
        return self._local_provider

    def select_model(self, requested_model: str | None = None) -> dict[str, Any]:
        health = self.client.health()
        available = [str(model) for model in health.get("models", []) if model]
        if not health.get("ok"):
            if self.use_local_fallback:
                local = self._get_local_provider()
                if local:
                    return {
                        "ok": True,
                        "selected_model": self.LOCAL_MODEL_NAME,
                        "available_models": available,
                        "reason": "local_fallback_sentence_transformers",
                        "error": None,
                        "provider": "local",
                    }
            return {
                "ok": False,
                "selected_model": None,
                "available_models": available,
                "reason": "ollama_unavailable",
                "error": health.get("error"),
            }
        if requested_model:
            if requested_model == self.LOCAL_MODEL_NAME:
                local = self._get_local_provider()
                if local:
                    return {
                        "ok": True,
                        "selected_model": self.LOCAL_MODEL_NAME,
                        "available_models": available,
                        "reason": "local_model_requested",
                        "error": None,
                        "provider": "local",
                    }
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
        if self.use_local_fallback:
            local = self._get_local_provider()
            if local:
                return {
                    "ok": True,
                    "selected_model": self.LOCAL_MODEL_NAME,
                    "available_models": available,
                    "reason": "local_fallback_no_ollama_models",
                    "error": None,
                    "provider": "local",
                }
        return {
            "ok": False,
            "selected_model": None,
            "available_models": available,
            "reason": "no_embedding_model_installed",
            "error": "No se encontró un modelo de embeddings local permitido.",
        }

    def _embed_with_provider(self, text: str, model: str, provider: str) -> EmbeddingResult:
        if provider == "local":
            local = self._get_local_provider()
            if not local:
                return EmbeddingResult(ok=False, model=model, embeddings=[], error="Proveedor local no disponible")
            try:
                vector = local.embed(text)
                return EmbeddingResult(ok=True, model=model, embeddings=[vector], provider="local", error=None)
            except Exception as exc:
                return EmbeddingResult(ok=False, model=model, embeddings=[], error=str(exc))
        return self.client.embed(model, text)

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
        provider = selection.get("provider", "ollama")
        if not selection.get("ok") or not selected_model:
            return SemanticEmbeddingEvent(
                ok=False,
                document_id=document_id,
                model=model,
                error=selection.get("error"),
                model_selection_reason=str(selection.get("reason", "selection_failed")),
            )
        result: EmbeddingResult = self._embed_with_provider(
            str(document["normalized_content"]),
            str(selected_model),
            provider,
        )
        if not result.ok or not result.embeddings:
            return SemanticEmbeddingEvent(
                ok=False,
                document_id=document_id,
                model=str(selected_model),
                error=result.error or "No se produjo vector de embedding.",
                model_selection_reason=str(selection["reason"]),
                provider=provider,
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
            provider=provider,
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
        pending = self.store.list_documents(limit=limit)
        embedded_ids = {item["document_id"] for item in self.store.list_embeddings()}
        pending = [d for d in pending if d["document_id"] not in embedded_ids]
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
        local_available = False
        try:
            local = self._get_local_provider()
            local_available = local is not None
        except Exception:
            pass
        return {
            "status": "ok" if selection.get("ok") else "warning",
            "mode": "semantic-embedding-engine-2.0",
            "selection": selection,
            "local_fallback_available": local_available,
            "store": self.store.doctor(),
            "runner_integration": "active_2.0",
            "semantic_search": "active_2.0",
        }
