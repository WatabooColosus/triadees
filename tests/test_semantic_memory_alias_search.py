"""Prueba de causalidad del alias `semantic_memory` → `semantic_documents`.

La tabla `semantic_memory` quedó retirada: en producción nadie alcanzable la
escribe, mientras los documentos reales viven en `semantic_documents`.
`Bodega._search_semantic()` —la búsqueda por palabras clave de la memoria
semántica— apuntaba al gemelo muerto y devolvía `[]` siempre.
Docs: docs/debt/SEMANTIC_MEMORY_ALIAS.md.
"""

from __future__ import annotations

from pathlib import Path

from triade.core.bodega import Bodega
from triade.core.contracts import InputPacket
from triade.memory.semantic_store import SemanticMemoryStore


def test_keyword_search_reads_the_live_semantic_documents(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"

    store = SemanticMemoryStore(db_path=db_path)
    store.upsert_document(
        content="El sistema genera grafos internos desde el AST, no desde la documentación.",
        domain="observabilidad",
        source_type="manual",
        source_ref="tests/test_semantic_memory_alias_search.py",
        status="stable",
    )
    store.upsert_document(
        content="Borrador sin gobierno: la búsqueda no debe influir con él.",
        domain="observabilidad",
        source_type="manual",
        source_ref="tests/test_semantic_memory_alias_search.py",
        status="candidate",
    )

    bodega = Bodega(db_path=db_path)
    memory = bodega.recall(
        InputPacket(
            user_input="grafos internos",
            source="test",
            run_id="run-alias-search",
        )
    )

    matches = [
        m
        for m in memory.semantic_matches
        if m.get("retrieval_type") == "legacy_keyword"
    ]
    assert matches, (
        "la búsqueda por palabras clave debe devolver el documento vivo, no []"
    )
    assert any(m.get("domain") == "observabilidad" for m in matches)
    assert all(m.get("document_id") for m in matches), (
        "el rastro de memoria espera document_id en cada coincidencia"
    )
    assert all(m.get("status") in {"stable", "experimental"} for m in matches), (
        "un documento candidate no debe influir en la memoria"
    )
