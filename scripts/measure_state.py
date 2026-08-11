#!/usr/bin/env python3
"""Foto comparable del organismo: las mismas cifras antes y después.

Existe para que un informe BEFORE/AFTER no se construya con dos consultas
parecidas escritas en momentos distintos. Aquí las preguntas son una sola vez y
las dos fotos salen del mismo código, así que una diferencia en el informe es
una diferencia real y no un cambio de criterio al contar.

Dos cuidados que ya han costado un diagnóstico equivocado:

- Las ventanas de tiempo comparan con `strftime('%Y-%m-%dT...')` y no con
  `datetime('now')`. Las tablas guardan la marca ISO con 'T' y `datetime('now')`
  devuelve un espacio: comparadas como texto, el espacio es menor que la 'T' y
  la ventana «reciente» se traga filas viejas.
- Lo que no se puede contar sale como None, no como 0. Una tabla ausente y una
  tabla vacía no son la misma noticia.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DB = "triade/memory/triade.db"

#: Volumen por tabla. El nombre es la pregunta: cuántas hay.
COUNT_TABLES = (
    "runs",
    "autonomous_tasks",
    "learning_queue",
    "learning_evidence",
    "semantic_documents",
    "semantic_governance_events",
    "knowledge_patterns",
    "planning_graph",
    "improvement_proposals",
    "improvement_canaries",
    "improvement_canary_observations",
    "improvement_history",
)


def _count(
    conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()
) -> int | None:
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else None


def _group(conn: sqlite3.Connection, sql: str) -> dict[str, int]:
    try:
        return {str(k): int(v) for k, v in conn.execute(sql).fetchall()}
    except sqlite3.Error:
        return {}


def measure(db_path: str = DB) -> dict[str, Any]:
    path = Path(db_path).resolve()
    snapshot: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "db_path": str(path),
        "db_size_bytes": path.stat().st_size if path.exists() else None,
    }
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        snapshot["counts"] = {
            table: _count(conn, f"select count(*) from {table}")
            for table in COUNT_TABLES
        }
        snapshot["learning_queue_by_status"] = _group(
            conn, "select status,count(*) from learning_queue group by status"
        )
        snapshot["semantic_documents_by_status"] = _group(
            conn, "select status,count(*) from semantic_documents group by status"
        )
        snapshot["tasks_by_status"] = _group(
            conn, "select status,count(*) from autonomous_tasks group by status"
        )
        snapshot["planning_graph_by_status"] = _group(
            conn, "select status,count(*) from planning_graph group by status"
        )

        # El circuito cognitivo, contado por etapas.
        snapshot["learning"] = {
            "evidence_verified": _count(
                conn,
                "select count(*) from learning_queue where status='evidence_verified'",
            ),
            "consolidated": _count(
                conn, "select count(*) from learning_queue where status='consolidated'"
            ),
            "with_causal_uses": _count(
                conn, "select count(*) from learning_queue where run_use_count>0"
            ),
            "total_causal_uses": _count(
                conn, "select coalesce(sum(run_use_count),0) from learning_queue"
            ),
            "ready_to_consolidate": _count(
                conn,
                """select count(*) from learning_queue
                   where status='evidence_verified'
                     and run_use_count>=3 and avg_outcome_score>=0.7""",
            ),
            "stable_documents": _count(
                conn, "select count(*) from semantic_documents where status='stable'"
            ),
            "stable_from_pipeline": _count(
                conn,
                """select count(*) from semantic_documents
                   where status='stable' and source_type='learning_pipeline'""",
            ),
        }

        snapshot["dead_letters"] = {
            "total": _count(
                conn, "select count(*) from autonomous_tasks where status='dead_letter'"
            ),
            "last_24h": _count(
                conn,
                """select count(*) from autonomous_tasks
                   where status='dead_letter'
                     and updated_at > strftime('%Y-%m-%dT%H:%M:%S','now','-1 day')""",
            ),
            "by_type": _group(
                conn,
                """select task_type,count(*) from autonomous_tasks
                   where status='dead_letter' group by task_type""",
            ),
        }
        snapshot["in_flight"] = _group(
            conn,
            """select status,count(*) from autonomous_tasks
               where status in ('leased','running','claimed') group by status""",
        )
        snapshot["tasks_completed_last_hour"] = _count(
            conn,
            """select count(*) from autonomous_tasks
               where status='completed'
                 and updated_at > strftime('%Y-%m-%dT%H:%M:%S','now','-1 hour')""",
        )

        snapshot["integrity"] = conn.execute("pragma integrity_check").fetchone()[0]
        snapshot["foreign_key_violations"] = len(
            conn.execute("pragma foreign_key_check").fetchall()
        )
    finally:
        conn.close()

    try:
        from triade.runtime.service_supervision import build_service_supervision

        snapshot["supervision"] = build_service_supervision()
    except (OSError, ImportError, RuntimeError, ValueError) as exc:
        snapshot["supervision"] = {"error": type(exc).__name__}

    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default=None, help="fichero JSON donde guardar la foto"
    )
    parser.add_argument("--db", default=DB)
    args = parser.parse_args()

    snapshot = measure(args.db)
    text = json.dumps(snapshot, indent=2, ensure_ascii=False)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"foto guardada en {out}")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
