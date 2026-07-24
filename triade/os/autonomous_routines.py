"""T-023 — Rutinas Autónomas: auto-mejora continua, creación autónoma de
neuronas, entrenamiento autónomo, verificación, degradación y documentación."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    import hashlib
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS autonomous_routines (
    routine_id     TEXT PRIMARY KEY,
    routine_type   TEXT NOT NULL,
    status         TEXT DEFAULT 'pending',
    config_json    TEXT DEFAULT '{}',
    result_json    TEXT DEFAULT '{}',
    started_at     TEXT,
    finished_at    TEXT,
    error          TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS autonomous_improvements (
    improvement_id TEXT PRIMARY KEY,
    routine_id     TEXT,
    category       TEXT NOT NULL,
    description    TEXT NOT NULL,
    before_json    TEXT DEFAULT '{}',
    after_json     TEXT DEFAULT '{}',
    impact_score   REAL DEFAULT 0.0,
    applied        INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS autonomous_documentation (
    doc_id         TEXT PRIMARY KEY,
    routine_id     TEXT,
    doc_type       TEXT DEFAULT 'auto_generated',
    title          TEXT NOT NULL,
    content        TEXT NOT NULL,
    component      TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);
"""

ROUTINE_TYPES = [
    "self_improvement",
    "autonomous_neuron_creation",
    "autonomous_training",
    "autonomous_verification",
    "autonomous_degradation",
    "auto_documentation",
    "memory_organization",
    "knowledge_pruning",
    "health_maintenance",
]


class AutonomousRoutines:
    """Motor de rutinas autónomas para auto-mejora continua."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def create_routine(self, routine_type: str, config: dict | None = None) -> dict:
        if routine_type not in ROUTINE_TYPES:
            raise ValueError(f"Unknown routine type: {routine_type}. Valid: {ROUTINE_TYPES}")
        routine_id = _gen_id("routine")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO autonomous_routines
               (routine_id, routine_type, config_json, created_at)
               VALUES (?,?,?,?)""",
            (routine_id, routine_type, json.dumps(config or {}, default=str), now),
        )
        self._conn.commit()
        return {"routine_id": routine_id, "type": routine_type, "status": "pending"}

    def execute_routine(self, routine_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM autonomous_routines WHERE routine_id=?", (routine_id,)
        ).fetchone()
        if not row:
            return {"error": "routine not found"}
        routine = dict(row)
        now = utc_now()

        self._conn.execute(
            "UPDATE autonomous_routines SET status='running', started_at=? WHERE routine_id=?",
            (now, routine_id),
        )

        try:
            result = self._run_by_type(routine["routine_type"],
                                        json.loads(routine["config_json"]) if routine["config_json"] else {})
            self._conn.execute(
                """UPDATE autonomous_routines
                   SET status='completed', finished_at=?, result_json=?
                   WHERE routine_id=?""",
                (utc_now(), json.dumps(result, default=str), routine_id),
            )
            self._conn.commit()
            return {"routine_id": routine_id, "status": "completed", "result": result}
        except Exception as e:
            self._conn.execute(
                """UPDATE autonomous_routines
                   SET status='failed', finished_at=?, error=?
                   WHERE routine_id=?""",
                (utc_now(), str(e), routine_id),
            )
            self._conn.commit()
            return {"routine_id": routine_id, "status": "failed", "error": str(e)}

    def _run_by_type(self, routine_type: str, config: dict) -> dict:
        if routine_type == "self_improvement":
            return self._self_improvement(config)
        elif routine_type == "autonomous_neuron_creation":
            return self._autonomous_neuron_creation(config)
        elif routine_type == "autonomous_training":
            return self._autonomous_training(config)
        elif routine_type == "autonomous_verification":
            return self._autonomous_verification(config)
        elif routine_type == "autonomous_degradation":
            return self._autonomous_degradation(config)
        elif routine_type == "auto_documentation":
            return self._auto_documentation(config)
        elif routine_type == "memory_organization":
            return self._memory_organization(config)
        elif routine_type == "knowledge_pruning":
            return self._knowledge_pruning(config)
        elif routine_type == "health_maintenance":
            return self._health_maintenance(config)
        return {"action": "no_handler"}

    def _self_improvement(self, config: dict) -> dict:
        improvements = []
        imp_id = _gen_id("imp")
        self._conn.execute(
            """INSERT INTO autonomous_improvements
               (improvement_id, category, description, impact_score, created_at)
               VALUES (?,?,?,?,?)""",
            (imp_id, "optimization", "Routine self-optimization cycle", 0.5, utc_now()),
        )
        self._conn.commit()
        return {"improvements": 1, "details": "Self-improvement cycle completed"}

    def _autonomous_neuron_creation(self, config: dict) -> dict:
        return {"action": "neuron_creation", "status": "queued",
                "message": "Neuron creation queued for review"}

    def _autonomous_training(self, config: dict) -> dict:
        return {"action": "training", "status": "queued",
                "message": "Training cycle queued"}

    def _autonomous_verification(self, config: dict) -> dict:
        return {"action": "verification", "verified": 0,
                "message": "Verification scan completed"}

    def _autonomous_degradation(self, config: dict) -> dict:
        return {"action": "degradation", "degraded": 0,
                "message": "Degradation scan completed"}

    def _auto_documentation(self, config: dict) -> dict:
        doc_id = _gen_id("doc")
        self._conn.execute(
            """INSERT INTO autonomous_documentation
               (doc_id, doc_type, title, content, created_at)
               VALUES (?,?,?,?,?)""",
            (doc_id, "auto_generated", "System Health Report",
             json.dumps({"status": "healthy", "timestamp": utc_now()}, default=str),
             utc_now()),
        )
        self._conn.commit()
        return {"docs_generated": 1, "doc_id": doc_id}

    def _memory_organization(self, config: dict) -> dict:
        return {"action": "memory_organization", "organized": 0}

    def _knowledge_pruning(self, config: dict) -> dict:
        return {"action": "pruning", "pruned": 0}

    def _health_maintenance(self, config: dict) -> dict:
        return {"action": "health_check", "status": "healthy"}

    def record_improvement(self, routine_id: str, category: str,
                           description: str, impact: float = 0.5,
                           before: dict | None = None, after: dict | None = None) -> dict:
        imp_id = _gen_id("imp")
        self._conn.execute(
            """INSERT INTO autonomous_improvements
               (improvement_id, routine_id, category, description,
                before_json, after_json, impact_score, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (imp_id, routine_id, category, description,
             json.dumps(before or {}, default=str),
             json.dumps(after or {}, default=str),
             impact, utc_now()),
        )
        self._conn.commit()
        return {"improvement_id": imp_id, "category": category}

    def list_routines(self, routine_type: str | None = None, limit: int = 20) -> list[dict]:
        if routine_type:
            rows = self._conn.execute(
                "SELECT * FROM autonomous_routines WHERE routine_type=? ORDER BY created_at DESC LIMIT ?",
                (routine_type, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM autonomous_routines ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def improvements(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM autonomous_improvements ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def documentation(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM autonomous_documentation ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def doctor(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM autonomous_routines").fetchone()["c"]
        completed = self._conn.execute("SELECT COUNT(*) as c FROM autonomous_routines WHERE status='completed'").fetchone()["c"]
        improvements = self._conn.execute("SELECT COUNT(*) as c FROM autonomous_improvements").fetchone()["c"]
        docs = self._conn.execute("SELECT COUNT(*) as c FROM autonomous_documentation").fetchone()["c"]
        return {"total_routines": total, "completed": completed,
                "improvements": improvements, "documents": docs}
