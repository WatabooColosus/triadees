"""Repara promociones y scores históricos sin borrar evidencia original."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

SYNTHETIC_STABLE = (
    "neurona-quiero-hagas-imagen-casa",
    "neurona-quiero-busques-formade-hacer",
    "neurona-pero-quiero-hagas-imagen",
)


def remediate(db_path: str | Path) -> dict:
    now = datetime.now(UTC).isoformat()
    db_path = Path(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS evidence_remediation_audit(
            id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT, entity_id TEXT,
            before_json TEXT, after_json TEXT, reason TEXT, created_at TEXT)""")
        changed_neurons = []
        for name in SYNTHETIC_STABLE:
            row = conn.execute(
                "SELECT id,name,status,created_by FROM neurons WHERE name=?", (name,)
            ).fetchone()
            if row and row["status"] == "stable":
                before = dict(row)
                conn.execute(
                    "UPDATE neurons SET status='experimental',updated_at=? WHERE id=?",
                    (now, row["id"]),
                )
                after = {**before, "status": "experimental"}
                conn.execute(
                    "INSERT INTO evidence_remediation_audit(entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        "neuron",
                        name,
                        json.dumps(before),
                        json.dumps(after),
                        "stable promotion relied on synthetic pulse evidence",
                        now,
                    ),
                )
                changed_neurons.append(name)
        rows = conn.execute(
            "SELECT candidate_id,run_use_count,run_outcome_scores,avg_outcome_score FROM learning_queue WHERE abs(avg_outcome_score-0.80)<0.000001"
        ).fetchall()
        for row in rows:
            before = dict(row)
            after = {
                **before,
                "run_use_count": 0,
                "run_outcome_scores": "[]",
                "avg_outcome_score": 0.0,
            }
            conn.execute(
                "UPDATE learning_queue SET run_use_count=0,run_outcome_scores='[]',avg_outcome_score=0.0,updated_at=? WHERE candidate_id=?",
                (now, row["candidate_id"]),
            )
            conn.execute(
                "INSERT INTO evidence_remediation_audit(entity_type,entity_id,before_json,after_json,reason,created_at) VALUES(?,?,?,?,?,?)",
                (
                    "learning_candidate",
                    row["candidate_id"],
                    json.dumps(before),
                    json.dumps(after),
                    "legacy automatic 0.80 score invalidated; content retained",
                    now,
                ),
            )
    return {
        "status": "completed",
        "neurons_reverted": changed_neurons,
        "scores_recalibrated": len(rows),
        "destructive_delete": False,
        "at": now,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="triade/memory/triade.db")
    print(json.dumps(remediate(parser.parse_args().db), ensure_ascii=False, indent=2))
