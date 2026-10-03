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


def test_fts5_index_tracks_new_episodic_rows_when_available(tmp_path) -> None:
    db_path = tmp_path / "triade.db"
    bodega = Bodega(db_path=db_path)
    if not bodega.fts5_enabled:
        return

    with bodega._connect() as conn:
        conn.execute(
            """INSERT INTO episodic_memory
               (run_id, title, content, summary, tags, confidence)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                None,
                "Continuidad",
                "La Bodega conserva un episodio ligero y recuperable.",
                "episodio ligero",
                "bodega,memoria",
                0.8,
            ),
        )

    matches = bodega._search_episodic("episodio recuperable", limit=5)
    assert matches
    assert matches[0]["title"] == "Continuidad"
