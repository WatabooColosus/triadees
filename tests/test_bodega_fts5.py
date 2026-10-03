"""Bodega usa FTS5 cuando SQLite lo ofrece y conserva fallback compatible."""

from __future__ import annotations

from triade.core.bodega import Bodega
from triade.memory.semantic_store import SemanticMemoryStore


def test_bodega_text_recall_survives_with_or_without_fts5(tmp_path) -> None:
    db_path = tmp_path / "triade.db"
    bodega = Bodega(db_path=db_path)
    store = SemanticMemoryStore(db_path=db_path)
    document = store.upsert_document(
        "La memoria verificable conserva continuidad entre sesiones.",
        domain="memory",
        status="stable",
    )

    matches = bodega._search_semantic("memoria continuidad", limit=5)

    assert matches
    assert matches[0]["document_id"] == document.document_id
    assert isinstance(bodega.fts5_enabled, bool)


def test_fts5_index_tracks_semantic_updates_when_available(tmp_path) -> None:
    db_path = tmp_path / "triade.db"
    bodega = Bodega(db_path=db_path)
    if not bodega.fts5_enabled:
        return

    store = SemanticMemoryStore(db_path=db_path)
    document = store.upsert_document(
        "Cristal inicial verificable.",
        domain="crystal",
        status="stable",
    )
    assert bodega._search_semantic("Cristal", limit=5)

    store.upsert_document(
        "Cristal evolucionado trazable.",
        domain="crystal",
        status="stable",
        document_id=document.document_id,
    )
    matches = bodega._search_semantic("evolucionado", limit=5)
    assert matches
    assert matches[0]["document_id"] == document.document_id
