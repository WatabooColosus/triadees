"""Persistencia de actividad de neuronas experimentales."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class NeuronActivityStore:
    """Guarda y consulta activaciones de neuronas por run."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path("triade/memory/schemas.sql")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(f"No existe el esquema de memoria: {self.schema_path}")
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            self._migrate_table(conn)

    def _migrate_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS neuron_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                neuron_id INTEGER,
                name TEXT NOT NULL,
                domain TEXT,
                status TEXT,
                activated INTEGER DEFAULT 1,
                diagnosis_count INTEGER DEFAULT 0,
                test_plan_count INTEGER DEFAULT 0,
                policy TEXT,
                activity_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (neuron_id) REFERENCES neurons(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_neuron_activity_run_id ON neuron_activity(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_neuron_activity_neuron_id ON neuron_activity(neuron_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_neuron_activity_name ON neuron_activity(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_neuron_activity_created_at ON neuron_activity(created_at)")

    def store_activity(self, *, run_id: str, activity: dict[str, Any]) -> list[int]:
        """Persiste activaciones de experimental_neuron_activity."""
        if not activity.get("active"):
            return []

        inserted: list[int] = []
        with self._connect() as conn:
            for activation in activity.get("activations") or []:
                if not isinstance(activation, dict):
                    continue

                output = activation.get("output") or {}
                diagnosis = output.get("diagnosis") or []
                test_plan = output.get("test_plan") or []

                diagnosis_count = len(diagnosis) if isinstance(diagnosis, list) else 0
                test_plan_count = len(test_plan) if isinstance(test_plan, list) else 0

                cursor = conn.execute(
                    """
                    INSERT INTO neuron_activity (
                        run_id, neuron_id, name, domain, status, activated,
                        diagnosis_count, test_plan_count, policy, activity_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        activation.get("neuron_id"),
                        str(activation.get("name") or "unknown"),
                        activation.get("domain"),
                        activation.get("status"),
                        1 if activation.get("active", True) else 0,
                        diagnosis_count,
                        test_plan_count,
                        activation.get("policy"),
                        json.dumps(activation, ensure_ascii=False),
                    ),
                )
                inserted.append(int(cursor.lastrowid))

        return inserted

    def record_run_activity(self, run_id: str, activity: dict[str, Any]) -> list[int]:
        """Alias semántico usado por TriadeRunner para registrar actividad de un run."""
        return self.store_activity(run_id=run_id, activity=activity)

    def list_activity(self, *, name: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if name:
                rows = conn.execute(
                    """
                    SELECT id, run_id, neuron_id, name, domain, status, activated,
                           diagnosis_count, test_plan_count, policy, activity_json, created_at
                    FROM neuron_activity
                    WHERE name = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (name, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, run_id, neuron_id, name, domain, status, activated,
                           diagnosis_count, test_plan_count, policy, activity_json, created_at
                    FROM neuron_activity
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        return [self._decode(dict(row)) for row in rows]

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        try:
            row["activity_json"] = json.loads(row.get("activity_json") or "{}")
        except json.JSONDecodeError:
            row["activity_json"] = {}
        row["activated"] = bool(row.get("activated"))
        return row
