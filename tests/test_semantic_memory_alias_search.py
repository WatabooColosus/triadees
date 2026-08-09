"""El alias `semantic_memory` → `semantic_documents` en la búsqueda por texto.

`Bodega._search_semantic()` —la búsqueda por palabras clave de la memoria
semántica— consultaba `semantic_memory`, una tabla con 0 filas en la base viva,
mientras los documentos reales viven en `semantic_documents` (299 el 2026-08-09).
Devolvía `[]` para cualquier consulta.

Reapuntarla no basta: el canal de palabras clave es el único que corre **aunque
el recall vectorial esté apagado**, y en ese caso el run no llega nunca a
`SemanticMemoryGovernance.govern_memory()`. Por eso el gobierno 1.9E se aplica
aquí en SQL —`stable` por defecto, `experimental` sólo si el run lo autoriza,
`candidate` y `rejected` nunca— y otra vez en gobierno cuando el run pasa por él.

Docs: docs/debt/SEMANTIC_MEMORY_ALIAS.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.bodega import Bodega
from triade.core.contracts import InputPacket, MemoryPacket
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_store import SemanticMemoryStore

CONSULTA = "grafos internos"
CONTENIDO = "Los grafos internos salen del AST, no de la documentación."
FUENTE = "tests/test_semantic_memory_alias_search.py"


def _sembrar(db_path: Path, status: str) -> str:
    """Un documento con el estado pedido, sin pasar por transiciones."""
    store = SemanticMemoryStore(db_path=db_path)
    return store.upsert_document(
        content=CONTENIDO,
        domain="observabilidad",
        source_type="manual",
        source_ref=FUENTE,
        status=status,
    ).document_id


def _keyword_matches(
    db_path: Path, allow_experimental: bool = False
) -> list[dict[str, Any]]:
    memoria = Bodega(db_path=db_path).recall(
        InputPacket(
            user_input=CONSULTA, source="test", run_id=f"run-{allow_experimental}"
        ),
        semantic_allow_experimental=allow_experimental,
    )
    return [
        m
        for m in memoria.semantic_matches
        if m.get("retrieval_type") == "legacy_keyword"
    ]


# --- 1. El canal vivo: lo que #93 reactiva -----------------------------------


def test_stable_por_palabras_clave_aparece(tmp_path: Path) -> None:
    """ANTES: 0 coincidencias contra `semantic_memory`. DESPUÉS: el documento."""
    _sembrar(tmp_path / "triade.db", "stable")

    matches = _keyword_matches(tmp_path / "triade.db")

    assert len(matches) == 1
    assert matches[0]["value"] == CONTENIDO
    assert matches[0]["domain"] == "observabilidad"
    assert matches[0]["status"] == "stable"


# --- 2..5. La política 1.9E, estado por estado -------------------------------


def test_candidate_por_palabras_clave_no_aparece(tmp_path: Path) -> None:
    _sembrar(tmp_path / "triade.db", "candidate")

    assert _keyword_matches(tmp_path / "triade.db") == []


def test_rejected_por_palabras_clave_no_aparece(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    document_id = _sembrar(db_path, "candidate")
    SemanticMemoryGovernance(db_path=db_path).transition_document(
        document_id, "rejected", "Contenido descartado en la prueba.", "test"
    )

    assert _keyword_matches(db_path) == []


def test_experimental_sin_autorizacion_no_aparece(tmp_path: Path) -> None:
    """El fallo que abrió esta auditoría: `status IN ('stable','experimental')`.

    Un documento `experimental` influía en cualquier run por el simple hecho de
    coincidir por texto, sin que nadie lo autorizara.
    """
    _sembrar(tmp_path / "triade.db", "experimental")

    assert _keyword_matches(tmp_path / "triade.db", allow_experimental=False) == []


def test_experimental_con_autorizacion_explicita_aparece(tmp_path: Path) -> None:
    """La autorización viaja de verdad: API → Runner → `Bodega.recall`.

    Es el mismo interruptor que ya gobernaba el canal vectorial
    (`semantic_allow_experimental`), no un segundo sistema de gobierno.
    """
    _sembrar(tmp_path / "triade.db", "experimental")

    matches = _keyword_matches(tmp_path / "triade.db", allow_experimental=True)

    assert len(matches) == 1
    assert matches[0]["status"] == "experimental"


# --- 6..7. Firma de proveniencia de lo autorizado ----------------------------


def test_cada_match_autorizado_conserva_document_id(tmp_path: Path) -> None:
    document_id = _sembrar(tmp_path / "triade.db", "stable")

    matches = _keyword_matches(tmp_path / "triade.db")

    assert [m["document_id"] for m in matches] == [document_id]


def test_cada_match_autorizado_conserva_source_ref(tmp_path: Path) -> None:
    _sembrar(tmp_path / "triade.db", "stable")

    matches = _keyword_matches(tmp_path / "triade.db")

    assert all(m["source_ref"] == FUENTE for m in matches)


# --- El segundo cerrojo: gobierno, no sólo SQL -------------------------------


def test_gobierno_no_sella_las_palabras_clave_como_autorizadas(
    tmp_path: Path,
) -> None:
    """`govern_memory()` marcaba todo match no vectorial `allowed_to_influence`.

    Bastaba con que un recuerdo llegara por el canal de texto para saltarse la
    política. Ahora los dos canales pasan por el mismo gate: si el documento no
    puede influir, tampoco influye por haber coincidido por palabras.
    """
    db_path = tmp_path / "triade.db"
    document_id = _sembrar(db_path, "candidate")
    memoria = MemoryPacket(
        run_id="run-keyword-governance",
        semantic_matches=[
            {
                "document_id": document_id,
                "value": CONTENIDO,
                "domain": "observabilidad",
                "source_ref": FUENTE,
                "status": "candidate",
                "retrieval_type": "legacy_keyword",
            }
        ],
        semantic_recall={"enabled": True, "status": "ok"},
        confidence=0.8,
    )

    gobernada = SemanticMemoryGovernance(db_path=db_path).govern_memory(memoria)

    politica = gobernada.semantic_recall["governance"]
    assert gobernada.semantic_matches == []
    assert politica["quarantined_keyword_matches"] == 1
    assert politica["allowed_keyword_matches"] == 0
    assert politica["decisions"][0]["channel"] == "keyword"
    assert politica["decisions"][0]["allowed_to_influence"] is False


def test_gobierno_autoriza_las_palabras_clave_de_un_documento_stable(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "triade.db"
    _sembrar(db_path, "stable")
    bodega = Bodega(db_path=db_path)
    memoria = bodega.recall(
        InputPacket(user_input=CONSULTA, source="test", run_id="run-keyword-stable")
    )
    memoria.semantic_recall["enabled"] = True

    gobernada = SemanticMemoryGovernance(db_path=db_path).govern_memory(memoria)

    politica = gobernada.semantic_recall["governance"]
    assert politica["allowed_keyword_matches"] == 1
    assert politica["quarantined_keyword_matches"] == 0
    assert gobernada.semantic_matches[0]["allowed_to_influence"] is True
    assert gobernada.semantic_matches[0]["document_status"] == "stable"
    assert gobernada.semantic_matches[0]["source_ref"] == FUENTE


# --- La tabla vieja no resucita ----------------------------------------------


def test_la_busqueda_ya_no_depende_de_semantic_memory(tmp_path: Path) -> None:
    """Una fila `stable` en la tabla vieja no vuelve a colarse en el recall.

    No es una prueba de que `semantic_memory` esté retirada —no lo está, ver
    docs/debt/SEMANTIC_MEMORY_ALIAS.md— sino de que este lector ya no la mira.
    """
    db_path = tmp_path / "triade.db"
    bodega = Bodega(db_path=db_path)
    with bodega._connect() as conn:
        conn.execute(
            "INSERT INTO semantic_memory (key, value, domain, source_ref, confidence, status)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("grafos", CONTENIDO, "observabilidad", FUENTE, 1.0, "stable"),
        )

    assert _keyword_matches(db_path) == []
