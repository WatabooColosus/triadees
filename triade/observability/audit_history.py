"""Lectura acotada de bitácoras operativas e históricas.

Las cargas JSON pueden contener contexto interno, por lo que esta vista sólo
expone identificadores, decisiones y marcas de tiempo necesarias para auditar
el efecto. Todas las conexiones son SQLite ``mode=ro``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.db import sqlite3

from .runtime_graph import open_readonly


def _rows(
    connection: sqlite3.Connection, query: str, limit: int
) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(query, (limit,)).fetchall()]


def build_audit_history(db_path: str | Path, *, limit: int = 20) -> dict[str, Any]:
    """Devuelve evidencia reciente de cuatro bitácoras sin modificar la base."""
    bounded_limit = min(max(int(limit), 1), 100)
    connection = open_readonly(Path(db_path))
    if connection is None:
        return {
            "status": "unavailable",
            "database": str(Path(db_path).resolve()),
            "sources": {},
            "simulated": False,
        }
    try:
        sources = {
            "hardware_senses": _rows(
                connection,
                """SELECT id, recorded_at
                FROM hardware_senses ORDER BY id DESC LIMIT ?""",
                bounded_limit,
            ),
            "engineering_evolution_events": _rows(
                connection,
                """SELECT id, evolution_id, event, decision, created_at
                FROM engineering_evolution_events ORDER BY id DESC LIMIT ?""",
                bounded_limit,
            ),
            "evidence_remediation_audit": _rows(
                connection,
                """SELECT id, entity_type, entity_id, reason, created_at
                FROM evidence_remediation_audit ORDER BY id DESC LIMIT ?""",
                bounded_limit,
            ),
            "neuron_certification_transitions": _rows(
                connection,
                """SELECT transition_id, neuron_id, from_status, to_status,
                    reason, rollback_ref, created_at
                FROM neuron_certification_transitions
                ORDER BY created_at DESC LIMIT ?""",
                bounded_limit,
            ),
        }
    except sqlite3.Error as exc:
        return {
            "status": "error",
            "database": str(Path(db_path).resolve()),
            "error": str(exc),
            "sources": {},
            "simulated": False,
        }
    finally:
        connection.close()
    return {
        "status": "ok",
        "database": str(Path(db_path).resolve()),
        "limit": bounded_limit,
        "counts": {table: len(rows) for table, rows in sources.items()},
        "sources": sources,
        "simulated": False,
    }
