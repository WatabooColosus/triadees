"""Baseline del circuito de aprendizaje sobre copia consistente de la base real.

No escribe en producción: abre `mode=ro` y copia con `Connection.backup()`.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
PROD = REPO / "triade/memory/triade.db"


def make_copy(outdir: Path) -> Path:
    copia = outdir / "triade-copy.db"
    src = sqlite3.connect(f"file:{PROD}?mode=ro", uri=True)
    dst = sqlite3.connect(copia)
    src.backup(dst)
    dst.close()
    src.close()
    return copia


def measure(db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }

    def rows(sql: str) -> list[dict[str, Any]]:
        try:
            return [dict(r) for r in conn.execute(sql).fetchall()]
        except sqlite3.Error as exc:
            return [{"error": str(exc)}]

    def scalar(sql: str) -> Any:
        try:
            r = conn.execute(sql).fetchone()
            return r[0] if r else None
        except sqlite3.Error as exc:
            return f"ERROR: {exc}"

    out: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "tables_total": len(tables),
        "tables_present": {
            t: (t in tables)
            for t in (
                "learning_queue",
                "learning_evidence",
                "improvement_proposals",
                "verification_reports",
                "semantic_documents",
                "semantic_embeddings",
                "knowledge_patterns",
                "stable_memory",
                "runs",
                "autonomous_tasks",
                "neurons",
            )
        },
    }

    out["learning_queue"] = {
        "total": scalar("SELECT count(*) FROM learning_queue"),
        "por_estado": rows(
            "SELECT status, count(*) n FROM learning_queue GROUP BY status ORDER BY n DESC"
        ),
        "por_dominio": rows(
            "SELECT domain, count(*) n FROM learning_queue GROUP BY domain ORDER BY n DESC LIMIT 20"
        ),
        "por_source_type": rows(
            "SELECT source_type, count(*) n FROM learning_queue GROUP BY source_type ORDER BY n DESC"
        ),
        "por_usos": rows(
            "SELECT CASE WHEN run_use_count IS NULL OR run_use_count=0 THEN '0'"
            " WHEN run_use_count<3 THEN '1-2' WHEN run_use_count<10 THEN '3-9'"
            " ELSE '10+' END tramo, count(*) n FROM learning_queue GROUP BY tramo ORDER BY n DESC"
        ),
        "score_stats": rows(
            "SELECT min(avg_outcome_score) mn, max(avg_outcome_score) mx,"
            " avg(avg_outcome_score) media, count(avg_outcome_score) con_score FROM learning_queue"
        ),
        "riesgo": rows(
            "SELECT risk_level, count(*) n FROM learning_queue GROUP BY risk_level"
        ),
    }

    out["learning_evidence"] = {
        "total": scalar("SELECT count(*) FROM learning_evidence"),
        "por_estado": rows(
            "SELECT status, count(*) n FROM learning_evidence GROUP BY status"
        ),
        "filas": rows("SELECT * FROM learning_evidence LIMIT 20"),
        "columnas": [
            r[1] for r in conn.execute("PRAGMA table_info(learning_evidence)")
        ],
    }

    # ¿Cuántos candidatos tienen evidencia? El enlace es por subject/candidate.
    out["cobertura_evidencia"] = {
        "candidatos_sin_evidencia": scalar(
            "SELECT count(*) FROM learning_queue q WHERE NOT EXISTS ("
            " SELECT 1 FROM learning_evidence e WHERE e.subject_id = q.candidate_id"
            " OR e.learning_id = q.candidate_id)"
        ),
    }

    out["verification_reports"] = {
        "total": scalar("SELECT count(*) FROM verification_reports"),
        "columnas": [
            r[1] for r in conn.execute("PRAGMA table_info(verification_reports)")
        ],
    }
    out["semantica"] = {
        "documentos": scalar("SELECT count(*) FROM semantic_documents"),
        "doc_por_estado": rows(
            "SELECT status, count(*) n FROM semantic_documents GROUP BY status"
        ),
        "embeddings": scalar("SELECT count(*) FROM semantic_embeddings"),
    }
    out["neuronas"] = rows(
        "SELECT name, status, triggers, updated_at FROM neurons ORDER BY id LIMIT 15"
    )

    out["pragmas"] = {
        "integrity_check": scalar("PRAGMA integrity_check"),
        "journal_mode": scalar("PRAGMA journal_mode"),
        "foreign_keys": scalar("PRAGMA foreign_keys"),
        "busy_timeout": scalar("PRAGMA busy_timeout"),
        "foreign_key_check_violaciones": len(rows("PRAGMA foreign_key_check")),
    }
    conn.close()
    return out


def main() -> int:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    outdir = REPO / "runs/learning-effectiveness-audit" / ts
    outdir.mkdir(parents=True, exist_ok=True)
    copia = make_copy(outdir)
    data = measure(copia)
    data["copy_path"] = str(copia)
    (outdir / "baseline.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
    print(f"\n>>> {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
