"""Tests del motor de embeddings semánticos locales 1.9B."""

from __future__ import annotations

from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_store import SemanticMemoryStore
from triade.models.ollama_client import EmbeddingResult

MIGRATION = "triade/memory/migrations/001_9A_semantic_memory.sql"


class FakeEmbeddingClient:
    def __init__(self, models: list[str] | None = None, fail: bool = False) -> None:
        self.models = models or ["nomic-embed-text:latest"]
        self.fail = fail
        self.requests: list[tuple[str, str]] = []

    def health(self) -> dict[str, object]:
        return {"ok": True, "models": self.models, "base_url": "fake://ollama"}

    def embed(
        self,
        model: str,
        input_text: str,
        truncate: bool = True,
        dimensions: int | None = None,
    ) -> EmbeddingResult:
        self.requests.append((model, input_text))
        if self.fail:
            return EmbeddingResult(ok=False, model=model, error="embedding failed")
        return EmbeddingResult(ok=True, model=model, embeddings=[[0.1, 0.2, 0.3]])


class UnavailableClient:
    def health(self) -> dict[str, object]:
        return {"ok": False, "models": [], "error": "offline"}


def make_engine(
    tmp_path, client, use_local_fallback: bool = True
) -> SemanticEmbeddingEngine:
    store = SemanticMemoryStore(
        db_path=tmp_path / "semantic.db", migration_path=MIGRATION
    )
    return SemanticEmbeddingEngine(
        store=store, client=client, use_local_fallback=use_local_fallback
    )


def test_selects_preferred_installed_embedding_model(tmp_path) -> None:
    engine = make_engine(
        tmp_path,
        FakeEmbeddingClient(models=["qwen3-embedding:0.6b", "nomic-embed-text:latest"]),
    )

    selection = engine.select_model()

    assert selection["ok"] is True
    assert selection["selected_model"] == "nomic-embed-text:latest"
    assert selection["reason"] == "preferred_installed_embedding_model"


def test_requested_model_must_be_installed(tmp_path) -> None:
    engine = make_engine(
        tmp_path, FakeEmbeddingClient(models=["nomic-embed-text:latest"])
    )

    selection = engine.select_model(requested_model="qwen3-embedding:0.6b")

    assert selection["ok"] is False
    assert selection["reason"] == "requested_model_not_installed"


def test_ingest_and_embed_persists_real_engine_result(tmp_path) -> None:
    client = FakeEmbeddingClient()
    engine = make_engine(tmp_path, client)

    result = engine.ingest_and_embed(
        "El Cristal conserva continuidad contextual.",
        domain="crystal",
        source_ref="test-1.9B",
    )
    document_id = result["document"]["document_id"]
    stored = engine.store.list_embeddings(document_id)

    assert result["embedding_event"]["ok"] is True
    assert result["embedding_event"]["model"] == "nomic-embed-text:latest"
    assert result["embedding_event"]["dimensions"] == 3
    assert client.requests[0][1] == "El Cristal conserva continuidad contextual."
    assert stored[0]["vector"] == [0.1, 0.2, 0.3]


def test_embed_document_records_failure_without_persisting_vector(tmp_path) -> None:
    engine = make_engine(tmp_path, FakeEmbeddingClient(fail=True))
    document = engine.store.upsert_document("Documento cuyo embedding falla")

    event = engine.embed_document(document.document_id)

    assert event.ok is False
    assert event.error == "embedding failed"
    assert engine.store.list_embeddings(document.document_id) == []


def test_embed_pending_only_processes_documents_without_vector(tmp_path) -> None:
    engine = make_engine(tmp_path, FakeEmbeddingClient())
    first = engine.store.upsert_document("Documento ya procesado")
    second = engine.store.upsert_document("Documento pendiente")
    engine.embed_document(first.document_id)

    result = engine.embed_pending()

    assert result["pending_found"] == 1
    assert result["embedded_ok"] == 1
    assert result["events"][0]["document_id"] == second.document_id


def test_doctor_reports_missing_ollama_or_embedding_model(tmp_path) -> None:
    unavailable = make_engine(
        tmp_path, UnavailableClient(), use_local_fallback=False
    ).doctor()
    no_model = make_engine(
        tmp_path,
        FakeEmbeddingClient(models=["llama3:latest"]),
        use_local_fallback=False,
    ).doctor()

    assert unavailable["status"] == "warning"
    assert unavailable["selection"]["reason"] == "ollama_unavailable"
    assert no_model["selection"]["reason"] == "no_embedding_model_installed"
    assert no_model["semantic_search"] == "active_2.0"


def test_hash_fallback_documents_are_invisible_to_the_query_model(tmp_path) -> None:
    """El vector guardado con otro modelo no lo encuentra la búsqueda de hoy.

    Medido en la base viva el 2026-08-10: 351 de 351 embeddings eran de
    `triade-local-hash:64` y la consulta se embebía con `nomic-embed-text`, así
    que `semantic_recall` reportaba `status: ok` con `matches_count: 0` y
    `skipped_model: 350` en cada run. `embed_pending` no los veía porque
    embedding tenían: sólo que ninguno servía.
    """
    engine = make_engine(tmp_path, FakeEmbeddingClient())
    documento = engine.store.upsert_document(
        content="La consolidación estable deja huella recuperable.",
        domain="learning",
        source_type="learning_pipeline",
        source_ref="run:test",
        status="stable",
    )
    engine.store.store_embedding(
        documento.document_id, "triade-local-hash:64", [0.5] * 64
    )

    assert engine.embed_pending()["pending_found"] == 0, (
        "embed_pending cuenta como resuelto un vector que la búsqueda descarta"
    )
    obsoletos = engine.stale_documents()
    assert obsoletos["stale_found"] == 1
    assert documento.document_id in obsoletos["documents"]


def test_reembed_stale_makes_documents_searchable_without_deleting_the_old_vector(
    tmp_path,
) -> None:
    engine = make_engine(tmp_path, FakeEmbeddingClient())
    documento = engine.store.upsert_document(
        content="Una preferencia explícita del usuario se recuerda.",
        domain="conversation",
        source_type="learning_pipeline",
        source_ref="run:test",
        status="stable",
    )
    engine.store.store_embedding(
        documento.document_id, "triade-local-hash:64", [0.5] * 64
    )

    resultado = engine.reembed_stale()

    assert resultado["status"] == "ok"
    assert resultado["selected_model"] == "nomic-embed-text:latest"
    assert resultado["reembedded_ok"] == 1
    assert engine.stale_documents()["stale_found"] == 0

    modelos = {
        item["embedding_model"]
        for item in engine.store.list_embeddings(documento.document_id)
    }
    assert modelos == {"triade-local-hash:64", "nomic-embed-text:latest"}, (
        "el vector viejo no se borra: la recuperación ya ignora los que no casan"
    )


def test_reembed_stale_does_nothing_without_an_embedding_model(tmp_path) -> None:
    engine = make_engine(tmp_path, UnavailableClient(), use_local_fallback=False)
    documento = engine.store.upsert_document(
        content="Sin modelo no se inventa un vector.",
        domain="conversation",
        source_type="learning_pipeline",
        source_ref="run:test",
        status="stable",
    )
    engine.store.store_embedding(
        documento.document_id, "triade-local-hash:64", [0.5] * 64
    )

    resultado = engine.reembed_stale()

    assert resultado["status"] == "skipped"
    assert resultado["reembedded_ok"] == 0


def test_a_degraded_model_never_rewrites_the_stable_index(tmp_path) -> None:
    """Con Ollama caído no se reindexa la memoria con el modelo de respaldo.

    `sentence-transformers` está instalado, así que basta con que Ollama se
    caiga un rato para que `select_model()` devuelva el respaldo local. Sin
    freno, el worker reembebería el corpus entero con un modelo peor y lo
    volvería a reembeber al volver Ollama: un vaivén que además deja la memoria
    indexada por el modelo degradado justo mientras dura la avería.
    """
    engine = make_engine(tmp_path, UnavailableClient(), use_local_fallback=True)
    documento = engine.store.upsert_document(
        content="Un modelo peor no reescribe lo que ya está indexado.",
        domain="conversation",
        source_type="learning_pipeline",
        source_ref="run:test",
        status="stable",
    )
    engine.store.store_embedding(
        documento.document_id, "nomic-embed-text:latest", [0.5] * 768
    )

    resultado = engine.reembed_stale()

    assert resultado["status"] == "skipped"
    assert str(resultado["reason"]).startswith("degraded:")
    assert resultado["reembedded_ok"] == 0
    modelos = {
        item["embedding_model"]
        for item in engine.store.list_embeddings(documento.document_id)
    }
    assert modelos == {"nomic-embed-text:latest"}
