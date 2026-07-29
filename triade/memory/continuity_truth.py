"""Verdad operativa sobre identidad y memoria longitudinal."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

MEMORY_QUESTION = re.compile(
    r"\b(recuerd|memoria|sesiones?|contexto anterior|olvid|persist|fuera de (?:la|cada) sesi[oó]n)\w*\b",
    re.IGNORECASE,
)

FALSE_EPHEMERAL_CLAIMS = (
    "todo el contenido",
    "desaparecerá",
    "desaparecera",
    "no guardo",
    "no tengo una memoria",
    "solo durante esta sesión",
    "solo durante esta sesion",
    "una vez que la sesión concluye",
    "una vez que la sesion concluye",
    "memoria está vacía",
    "memoria esta vacia",
)


def memory_truth_snapshot(db_path: str | Path) -> dict[str, Any]:
    path = Path(db_path)
    counts = {
        "runs": 0,
        "episodic_memory": 0,
        "semantic_documents": 0,
        "learning_queue": 0,
    }
    if path.is_file():
        with sqlite3.connect(path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in counts:
                if table in tables:
                    counts[table] = int(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    )
    return {
        "persistent": path.is_file(),
        "db_path": str(path),
        "counts": counts,
        "identity_continuous": True,
        "session_boundary_does_not_delete_memory": True,
        "recall_is_selective_not_total": True,
        "truth": (
            "Tríade conserva identidad, runs, episodios, documentos semánticos y candidatos en SQLite entre sesiones y reinicios. "
            "Recordar es selectivo: persistir no garantiza recuperar cada detalle en cada respuesta."
        ),
    }


def enforce_memory_truth(
    user_input: str, response: str, snapshot: dict[str, Any]
) -> tuple[str, list[str]]:
    lowered = response.lower()
    asks_memory = bool(MEMORY_QUESTION.search(user_input))
    contradicts = any(claim in lowered for claim in FALSE_EPHEMERAL_CLAIMS)
    states_continuity = any(
        claim in lowered
        for claim in (
            "memoria persistente",
            "persiste entre sesiones",
            "persisten entre sesiones",
            "fuera de cada sesión",
        )
    )
    if snapshot.get("persistent") and (
        (asks_memory and not states_continuity) or contradicts
    ):
        counts = snapshot.get("counts", {})
        corrected = (
            "Sí: conservo memoria persistente fuera de cada sesión. Mi identidad operativa sigue siendo Tríade Ω y la Bodega guarda "
            f"runs ({counts.get('runs', 0)}), episodios ({counts.get('episodic_memory', 0)}), documentos semánticos "
            f"({counts.get('semantic_documents', 0)}) y aprendizajes candidatos ({counts.get('learning_queue', 0)}) en SQLite. "
            "No recuerdo literalmente todo en cada respuesta: recupero lo relevante y distingo candidatos de memoria estable. "
            "Cerrar una sesión no borra esa memoria; una pérdida solo debería ocurrir por corrupción, borrado autorizado o falta de backup."
        )
        correction = (
            "false_ephemeral_memory_claim_replaced"
            if contradicts
            else "memory_continuity_answer_enforced"
        )
        return corrected, [correction]
    return response, []
