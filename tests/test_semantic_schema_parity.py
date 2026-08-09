"""`schemas.sql` y `001_9A_semantic_memory.sql` declaran el mismo contrato.

Las tablas semánticas nacían sólo por migración: una instalación nueva las tenía
si —y cuando— alguien instanciaba `SemanticMemoryStore`. Al declararlas también
en el esquema base aparecen dos fuentes para la misma tabla, y dos fuentes
derivan: alguien añade una columna en una y la otra crea la tabla sin ella,
`CREATE TABLE IF NOT EXISTS` calla, y la diferencia sólo se ve el día que una
consulta falla en la instalación equivocada.

Esta prueba no comprueba que las tablas «existan»: compara columna a columna,
índice a índice y clave a clave las dos bases que resultan de cada fichero.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
ESQUEMA_BASE = REPO_ROOT / "triade/memory/schemas.sql"
MIGRACION = REPO_ROOT / "triade/memory/migrations/001_9A_semantic_memory.sql"

#: Las tablas que ahora viven en los dos ficheros.
TABLAS = ("semantic_documents", "semantic_embeddings")


def _construir(db_path: Path, script: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(script.read_text(encoding="utf-8"))
    conn.commit()
    return conn


def _columnas(conn: sqlite3.Connection, tabla: str) -> list[tuple[Any, ...]]:
    """Nombre, tipo, NOT NULL, default y pertenencia a la clave primaria."""
    return [
        (fila[1], fila[2], fila[3], fila[4], fila[5])
        for fila in conn.execute(f"PRAGMA table_info({tabla})")
    ]


def _indices(conn: sqlite3.Connection, tabla: str) -> dict[str, Any]:
    """Índices con su unicidad y sus columnas; el nombre autogenerado de un
    UNIQUE inline (`sqlite_autoindex_…`) no se compara: lo pone SQLite."""
    resultado: dict[str, Any] = {}
    for fila in conn.execute(f"PRAGMA index_list({tabla})"):
        nombre, unico, origen = fila[1], fila[2], fila[3]
        columnas = tuple(c[2] for c in conn.execute(f"PRAGMA index_info('{nombre}')"))
        clave = f"auto:{columnas}" if nombre.startswith("sqlite_autoindex") else nombre
        resultado[clave] = (unico, origen, columnas)
    return resultado


def _claves_foraneas(conn: sqlite3.Connection, tabla: str) -> list[tuple[Any, ...]]:
    """Tabla referida, columnas y —lo que importa aquí— el ON DELETE."""
    return sorted(
        (fila[2], fila[3], fila[4], fila[5], fila[6])
        for fila in conn.execute(f"PRAGMA foreign_key_list({tabla})")
    )


def test_las_tablas_semanticas_tienen_el_mismo_contrato(tmp_path: Path) -> None:
    desde_esquema = _construir(tmp_path / "esquema.db", ESQUEMA_BASE)
    desde_migracion = _construir(tmp_path / "migracion.db", MIGRACION)

    for tabla in TABLAS:
        assert _columnas(desde_esquema, tabla) == _columnas(desde_migracion, tabla), (
            f"{tabla}: las columnas de schemas.sql y 001_9A ya no coinciden"
        )
        assert _indices(desde_esquema, tabla) == _indices(desde_migracion, tabla), (
            f"{tabla}: los índices de schemas.sql y 001_9A ya no coinciden"
        )
        assert _claves_foraneas(desde_esquema, tabla) == _claves_foraneas(
            desde_migracion, tabla
        ), f"{tabla}: las claves foráneas de schemas.sql y 001_9A ya no coinciden"


def test_una_instalacion_nueva_ya_no_espera_a_la_migracion(tmp_path: Path) -> None:
    """El esquema base solo: la búsqueda viva tiene dónde mirar desde el arranque."""
    conn = _construir(tmp_path / "solo_esquema.db", ESQUEMA_BASE)

    tablas = {
        fila[0]
        for fila in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    assert TABLAS[0] in tablas
    assert TABLAS[1] in tablas


def test_aplicar_la_migracion_sobre_el_esquema_base_es_idempotente(
    tmp_path: Path,
) -> None:
    """El orden real de arranque: `schemas.sql` y después la migración."""
    db_path = tmp_path / "ambos.db"
    conn = _construir(db_path, ESQUEMA_BASE)
    antes = {tabla: _columnas(conn, tabla) for tabla in TABLAS}

    conn.executescript(MIGRACION.read_text(encoding="utf-8"))
    conn.commit()

    assert {tabla: _columnas(conn, tabla) for tabla in TABLAS} == antes
