"""Rollback mechanism for neuron_factory: permite deshacer creaciones
de neuronas, entrenamientos y cambios de configuración."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    import hashlib
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS neuron_rollback_log (
    rollback_id    TEXT PRIMARY KEY,
    target_type    TEXT NOT NULL,
    target_id      TEXT NOT NULL,
    action         TEXT NOT NULL,
    snapshot_json  TEXT DEFAULT '{}',
    status         TEXT DEFAULT 'pending',
    rolled_back_at TEXT,
    error          TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);
"""


class NeuronRollback:
    """Registra snapshots antes de cambios y permite rollback."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def snapshot(self, target_type: str, target_id: str,
                 state: dict, action: str = "pre_change") -> dict:
        rollback_id = _gen_id("rb")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO neuron_rollback_log
               (rollback_id, target_type, target_id, action,
                snapshot_json, status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (rollback_id, target_type, target_id, action,
             json.dumps(state, default=str), "snapshotted", now),
        )
        self._conn.commit()
        return {"rollback_id": rollback_id, "target_type": target_type,
                "target_id": target_id, "action": action}

    def rollback(self, rollback_id: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM neuron_rollback_log WHERE rollback_id=?",
            (rollback_id,),
        ).fetchone()
        if not row:
            return {"error": "rollback not found"}
        snapshot = json.loads(row["snapshot_json"])
        self._conn.execute(
            """UPDATE neuron_rollback_log
               SET status='rolled_back', rolled_back_at=?
               WHERE rollback_id=?""",
            (utc_now(), rollback_id),
        )
        self._conn.commit()
        return {"rollback_id": rollback_id, "restored_state": snapshot,
                "target_type": row["target_type"], "target_id": row["target_id"]}

    def list_rollbackable(self, target_type: str | None = None) -> list[dict]:
        if target_type:
            rows = self._conn.execute(
                "SELECT * FROM neuron_rollback_log WHERE status='snapshotted' AND target_type=?",
                (target_type,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM neuron_rollback_log WHERE status='snapshotted'"
            ).fetchall()
        return [dict(r) for r in rows]

    def rollback_history(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM neuron_rollback_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def doctor(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM neuron_rollback_log").fetchone()["c"]
        pending = self._conn.execute("SELECT COUNT(*) as c FROM neuron_rollback_log WHERE status='snapshotted'").fetchone()["c"]
        rolled = self._conn.execute("SELECT COUNT(*) as c FROM neuron_rollback_log WHERE status='rolled_back'").fetchone()["c"]
        return {"total_snapshots": total, "pending": pending, "rolled_back": rolled}
