"""El diario de aprendizaje reportaba siempre cero actividad semántica.

`build_learning_journal` leía `semantic_memory`, una tabla con **cero filas y
ningún `INSERT` en todo el repositorio**. La actividad real vive en
`semantic_documents`, donde el pipeline de aprendizaje escribe desde hace
semanas: 379 filas medidas el 2026-08-11.

El efecto no era «un contador flojo». Esa madrugada el organismo consolidó tres
memorias estables —`sem-64378483949b44ce`, `sem-2f130119b3784051`,
`sem-a9d51f9d841d48a5`— y el diario siguió diciendo cero. Es la avería más cara
de este tipo: no falla, miente en voz baja, y quien mira el diario para saber si
el sistema consolida algo concluye que no.

El diario se sirve en `/api/runtime/learning-journal` y alimenta el heartbeat,
así que el lector estaba vivo: recibía el caso vacío para siempre.

Se aprovecha para renombrar la clave del payload. Se llamaba
`semantic_memory_activity` mientras pasaba a leer `semantic_documents`, y dejar
ese nombre habría creado justo el alias que este repositorio lleva meses
persiguiendo: un lector que dice una tabla y consulta otra.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.learning_journal import build_learning_journal


def _db(tmp_path: Path) -> Path:
    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            -- Mismo esquema que producción: si aquí faltan columnas, el test
            -- pasa contra una tabla que no existe tal cual en ningún sitio.
            CREATE TABLE semantic_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT,
                content TEXT,
                normalized_content TEXT,
                content_hash TEXT,
                domain TEXT,
                source_type TEXT,
                source_ref TEXT,
                metadata TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE semantic_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT, value TEXT, domain TEXT, source_ref TEXT,
                confidence REAL, status TEXT, created_at TEXT, updated_at TEXT
            );
            """
        )
    return db


def _insert_document(db: Path, document_id: str, status: str, created_at: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO semantic_documents "
            "(document_id, content, normalized_content, content_hash, domain, "
            " source_type, source_ref, metadata, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                document_id,
                "contenido",
                "contenido",
                f"hash-{document_id}",
                "conversation",
                "learning_pipeline",
                "run:test",
                "{}",
                status,
                created_at,
                created_at,
            ),
        )


def test_reporta_los_documentos_semanticos_recientes(tmp_path: Path) -> None:
    db = _db(tmp_path)
    from datetime import UTC, datetime

    ahora = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    _insert_document(db, "sem-1", "stable", ahora)
    _insert_document(db, "sem-2", "candidate", ahora)

    journal = build_learning_journal(db_path=db, since_hours=24, limit=10)
    actividad = journal["semantic_documents_activity"]

    assert actividad["count"] == 2
    ids = {fila["document_id"] for fila in actividad["latest"]}
    assert ids == {"sem-1", "sem-2"}


def test_la_tabla_muerta_ya_no_decide(tmp_path: Path) -> None:
    """Con `semantic_memory` vacía —como en producción— el diario ya no dice cero."""
    db = _db(tmp_path)
    from datetime import UTC, datetime

    ahora = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    _insert_document(db, "sem-consolidado", "stable", ahora)

    with sqlite3.connect(db) as conn:
        vacia = conn.execute("SELECT COUNT(*) FROM semantic_memory").fetchone()[0]
    assert vacia == 0, "la premisa del fallo: la tabla que se leía está vacía"

    journal = build_learning_journal(db_path=db, since_hours=24, limit=10)
    assert journal["semantic_documents_activity"]["count"] == 1


def test_la_clave_antigua_no_sobrevive(tmp_path: Path) -> None:
    """Un nombre que apunta a otra tabla es el alias que hay que evitar."""
    db = _db(tmp_path)
    journal = build_learning_journal(db_path=db, since_hours=24, limit=10)

    assert "semantic_documents_activity" in journal
    assert "semantic_memory_activity" not in journal


def test_lo_viejo_queda_fuera_de_la_ventana(tmp_path: Path) -> None:
    db = _db(tmp_path)
    _insert_document(db, "sem-antiguo", "stable", "2020-01-01 00:00:00")

    journal = build_learning_journal(db_path=db, since_hours=24, limit=10)
    assert journal["semantic_documents_activity"]["count"] == 0
