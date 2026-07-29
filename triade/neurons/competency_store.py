"""Persistencia de competencias, currículos y sesiones educativas."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CompetencyStore:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        migration = Path(__file__).resolve().parents[1] / "memory/migrations/010_neuron_education.sql"
        with self.connect() as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def ensure_competency(self, neuron_id: int, domain: str, name: str) -> dict[str, Any]:
        now = utc_now()
        competency_id = f"competency-{uuid4().hex[:16]}"
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO neuron_competencies
                (competency_id,neuron_id,domain,name,created_at,updated_at) VALUES(?,?,?,?,?,?)""",
                (competency_id, neuron_id, domain, name, now, now),
            )
            row = conn.execute(
                "SELECT * FROM neuron_competencies WHERE neuron_id=? AND domain=? AND name=?",
                (neuron_id, domain, name),
            ).fetchone()
        return dict(row) if row else {}

    def ensure_curriculum(self, neuron_id: int, mission_id: int | None, domain: str, objective: str) -> dict[str, Any]:
        now = utc_now()
        curriculum_id = f"curriculum-{uuid4().hex[:16]}"
        allowed = json.dumps(["repo", "document", "web", "node"], ensure_ascii=False)
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO neuron_curricula
                (curriculum_id,neuron_id,mission_id,domain,objective,allowed_source_types_json,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,'candidate',?,?)""",
                (curriculum_id, neuron_id, mission_id, domain, objective, allowed, now, now),
            )
            row = conn.execute("SELECT * FROM neuron_curricula WHERE neuron_id=? AND domain=?", (neuron_id, domain)).fetchone()
        return dict(row) if row else {}

    def record_session(self, *, curriculum_id: str, neuron_id: int, competency_id: str, state: str,
                       material_refs: list[str], independent_sources: int, lesson: dict[str, Any],
                       exercise: dict[str, Any], evaluation: dict[str, Any], result: str,
                       baseline_score: float | None = None, post_score: float | None = None) -> dict[str, Any]:
        session_id = f"education-{uuid4().hex[:16]}"
        now = utc_now()
        rollback_ref = f"education_session:{session_id}:archive_only"
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO neuron_education_sessions
                (session_id,curriculum_id,neuron_id,competency_id,state,material_refs_json,independent_source_count,
                 lesson_json,exercise_json,evaluation_json,baseline_score,post_score,result,rollback_ref,created_at,finished_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session_id, curriculum_id, neuron_id, competency_id, state, json.dumps(material_refs), independent_sources,
                 json.dumps(lesson, ensure_ascii=False), json.dumps(exercise, ensure_ascii=False),
                 json.dumps(evaluation, ensure_ascii=False), baseline_score, post_score, result, rollback_ref, now, now),
            )
            conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                (session_id, neuron_id, state, json.dumps({"result": result, "sources": independent_sources}), now),
            )
        return {"session_id": session_id, "state": state, "result": result, "rollback_ref": rollback_ref}
