"""Episodic Memory — experiencias con run_id, importancia, confianza,
versiones, olvido reversible, y integración con Qualia.

Migraciones formales, no CREATE TABLE IF NOT EXISTS.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now

log = logging.getLogger(__name__)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS episodic_memory (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    content       TEXT NOT NULL,
    summary       TEXT DEFAULT '',
    tags          TEXT DEFAULT '[]',
    importance    REAL NOT NULL DEFAULT 0.5,
    confidence    REAL NOT NULL DEFAULT 0.8,
    qualia_packet_id TEXT DEFAULT '',
    version       INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'active',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    forgotten_at  TEXT,
    forget_reason TEXT DEFAULT '',
    forget_policy TEXT DEFAULT '',
    forget_snapshot TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_ep_run ON episodic_memory(run_id);
CREATE INDEX IF NOT EXISTS idx_ep_tags ON episodic_memory(tags);
CREATE INDEX IF NOT EXISTS idx_ep_status ON episodic_memory(status);
CREATE INDEX IF NOT EXISTS idx_ep_importance ON episodic_memory(importance DESC);
CREATE TABLE IF NOT EXISTS episodic_memory_history (
    history_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id      INTEGER NOT NULL,
    version       INTEGER NOT NULL,
    content       TEXT NOT NULL,
    importance    REAL NOT NULL,
    confidence    REAL NOT NULL,
    tags          TEXT DEFAULT '[]',
    change_reason TEXT DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emh_entry ON episodic_memory_history(entry_id);
"""

MIGRATIONS = {
    1: SCHEMA_V1,
}


@dataclass
class EpisodicEntry:
    entry_id: int = 0
    run_id: str = ""
    title: str = ""
    content: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 0.8
    qualia_packet_id: str = ""
    version: int = 1
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""
    forgotten_at: str = ""
    forget_reason: str = ""
    forget_policy: str = ""
    forget_snapshot: dict[str, Any] = field(default_factory=dict)


class EpisodicMemory:
    """Gestiona experiencias episódicas con versionado, olvido reversible, y Qualia."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        row = self._conn.execute(
            "SELECT version FROM schema_migrations WHERE table_name='episodic_memory' ORDER BY version DESC LIMIT 1"
        ).fetchone()
        current_version = row["version"] if row else 0
        target_version = max(MIGRATIONS.keys())
        if current_version >= target_version:
            return
        for v in range(current_version + 1, target_version + 1):
            sql = MIGRATIONS.get(v)
            if sql:
                try:
                    self._conn.executescript(sql)
                    self._conn.execute(
                        "INSERT OR REPLACE INTO schema_migrations (table_name, version, applied_at) VALUES (?,?,?)",
                        ("episodic_memory", v, utc_now()),
                    )
                    self._conn.commit()
                    log.info("Applied episodic_memory migration v%d", v)
                except Exception as exc:
                    log.error("Migration v%d failed: %s", v, exc)
                    raise

    def store(
        self, content: str, run_id: str = "", title: str = "",
        summary: str = "", tags: list[str] | None = None,
        importance: float = 0.5, confidence: float = 0.8,
        qualia_packet_id: str = "",
    ) -> dict[str, Any]:
        importance = _clamp(importance)
        confidence = _clamp(confidence)
        now = utc_now()
        tags_str = json.dumps(tags or [], default=str)
        cur = self._conn.execute(
            """INSERT INTO episodic_memory
               (run_id, title, content, summary, tags, importance, confidence,
                qualia_packet_id, version, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,1,'active',?,?)""",
            (run_id, title, content, summary, tags_str, importance, confidence,
             qualia_packet_id, now, now),
        )
        entry_id = cur.lastrowid
        self._conn.commit()
        return {"entry_id": entry_id, "title": title, "importance": importance, "confidence": confidence}

    def update(self, entry_id: int, content: str | None = None, importance: float | None = None,
               confidence: float | None = None, tags: list[str] | None = None,
               change_reason: str = "") -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM episodic_memory WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return {"error": "not_found"}
        self._conn.execute(
            """INSERT INTO episodic_memory_history
               (entry_id, version, content, importance, confidence, tags, change_reason, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (entry_id, row["version"], row["content"], row["importance"],
             row["confidence"], row["tags"], change_reason, utc_now()),
        )
        new_content = content if content is not None else row["content"]
        new_importance = _clamp(importance) if importance is not None else row["importance"]
        new_confidence = _clamp(confidence) if confidence is not None else row["confidence"]
        new_tags = json.dumps(tags, default=str) if tags is not None else row["tags"]
        new_version = row["version"] + 1
        self._conn.execute(
            """UPDATE episodic_memory
               SET content=?, importance=?, confidence=?, tags=?,
                   version=?, updated_at=?
               WHERE id=?""",
            (new_content, new_importance, new_confidence, new_tags,
             new_version, utc_now(), entry_id),
        )
        self._conn.commit()
        return {"entry_id": entry_id, "new_version": new_version}

    def forget(self, entry_id: int, reason: str = "", policy: str = "manual") -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM episodic_memory WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return {"error": "not_found"}
        snapshot = {
            "content": row["content"], "importance": row["importance"],
            "confidence": row["confidence"], "tags": row["tags"],
            "version": row["version"],
        }
        now = utc_now()
        self._conn.execute(
            """UPDATE episodic_memory
               SET status='forgotten', forgotten_at=?, forget_reason=?,
                   forget_policy=?, forget_snapshot=?, updated_at=?
               WHERE id=?""",
            (now, reason, policy, json.dumps(snapshot, default=str), now, entry_id),
        )
        self._conn.commit()
        return {"entry_id": entry_id, "forgotten": True, "reason": reason}

    def restore(self, entry_id: int) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM episodic_memory WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return {"error": "not_found"}
        if row["status"] != "forgotten":
            return {"error": "not_forgotten"}
        self._conn.execute(
            """UPDATE episodic_memory
               SET status='active', forgotten_at=NULL, forget_reason='',
                   forget_policy='', forget_snapshot='{}', updated_at=?
               WHERE id=?""",
            (utc_now(), entry_id),
        )
        self._conn.commit()
        return {"entry_id": entry_id, "restored": True}

    def recall_by_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM episodic_memory WHERE run_id=? AND status='active' ORDER BY importance DESC",
            (run_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def recall_by_tags(self, tags: list[str], limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM episodic_memory WHERE status='active' ORDER BY importance DESC"
        ).fetchall()
        tag_set = set(tags)
        results: list[dict[str, Any]] = []
        for r in rows:
            r_tags = set(json.loads(r["tags"]) if r["tags"] else [])
            if tag_set & r_tags:
                results.append(self._row_to_dict(r))
                if len(results) >= limit:
                    break
        return results

    def recall_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM episodic_memory WHERE status='active' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_history(self, entry_id: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM episodic_memory_history WHERE entry_id=? ORDER BY version DESC",
            (entry_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) as c FROM episodic_memory WHERE status='active'").fetchone()["c"]
        forgotten = self._conn.execute("SELECT COUNT(*) as c FROM episodic_memory WHERE status='forgotten'").fetchone()["c"]
        avg_imp = self._conn.execute("SELECT AVG(importance) as a FROM episodic_memory WHERE status='active'").fetchone()["a"] or 0
        avg_conf = self._conn.execute("SELECT AVG(confidence) as a FROM episodic_memory WHERE status='active'").fetchone()["a"] or 0
        return {
            "total_entries": total, "forgotten": forgotten,
            "avg_importance": round(avg_imp, 3), "avg_confidence": round(avg_conf, 3),
        }

    def doctor(self) -> dict[str, Any]:
        return self.summary()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
        if d.get("forget_snapshot"):
            try:
                d["forget_snapshot"] = json.loads(d["forget_snapshot"])
            except (json.JSONDecodeError, TypeError):
                d["forget_snapshot"] = {}
        return d
