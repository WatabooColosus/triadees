"""PRAGMAs de durabilidad y concurrencia para la base SQLite de Tríade.

Motivo (auditoría 2026-07-31, hallazgo P1-04): la base de producción estaba en
`journal_mode=wal`, pero **ningún archivo del repositorio lo establecía**. WAL es
una propiedad persistente del fichero, así que estaba activo solo porque alguien
lo activó a mano en algún momento. Un despliegue nuevo, un restore a fichero nuevo
o un entorno de CI habrían arrancado en `journal_mode=delete`, sin lecturas
concurrentes durante escritura, con 2 procesos + 7 hilos + subprocesos por tarea
compitiendo por la misma base.

No se centralizan las conexiones (hay ~286 llamadas directas a `sqlite3.connect()`
en el repo y no existe un helper común): como el modo es persistente, basta con
aplicarlo **una vez, temprano y de forma idempotente** en cada entrypoint.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from triade.db import sqlite3

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "triade/memory/triade.db"


def default_db_path() -> str:
    return os.getenv("TRIADE_DB_PATH", DEFAULT_DB_PATH)


def ensure_durability_pragmas(db_path: str | Path | None = None) -> dict[str, Any]:
    """Garantiza `journal_mode=WAL` en la base indicada.

    Idempotente y no destructivo: si ya está en WAL, SQLite lo devuelve sin
    cambiar nada. Nunca lanza: un fallo aquí no debe impedir el arranque, pero sí
    queda registrado y reflejado en el valor de retorno.
    """
    path = Path(db_path or default_db_path())
    result: dict[str, Any] = {"db_path": str(path), "journal_mode": None}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            result["journal_mode"] = str(row[0]).lower() if row else None
        result["status"] = "ok" if result["journal_mode"] == "wal" else "unexpected"
    except (sqlite3.Error, OSError) as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("No se pudo asegurar journal_mode=WAL en %s: %s", path, exc)
    return result
