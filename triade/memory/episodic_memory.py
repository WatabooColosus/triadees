"""Episodic Memory — almacena experiencias y eventos con run_id,
importancia, confianza y tags para recall contextual."""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now


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
    created_at: str = ""


class EpisodicMemory:
    """Gestiona experiencias episódicas — eventos anclados a un run_id
    con importancia, confianza y recall por tags."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS episodic_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                title TEXT,
                content TEXT NOT NULL,
                summary TEXT,
                tags TEXT,
                importance REAL DEFAULT 0.5,
                confidence REAL DEFAULT 0.8,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ep_run ON episodic_memory(run_id);
            CREATE INDEX IF NOT EXISTS idx_ep_tags ON episodic_memory(tags);
        """)

    def store(self, content: str, run_id: str = "", title: str = "",
              summary: str = "", tags: list[str] | None = None,
              importance: float = 0.5, confidence: float = 0.8) -> dict:
        now = utc_now()
        tags_str = json.dumps(tags or [], default=str)
        cur = self._conn.execute(
            """INSERT INTO episodic_memory
               (run_id, title, content, summary, tags, importance, confidence, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, title, content, summary, tags_str, importance, confidence, now),
        )
        self._conn.commit()
        return {"entry_id": cur.lastrowid, "title": title, "importance": importance}

    def recall_by_run(self, run_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM episodic_memory WHERE run_id=? ORDER BY importance DESC",
            (run_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def recall_by_tags(self, tags: list[str], limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM episodic_memory ORDER BY importance DESC", ()
        ).fetchall()
        results = []
        tag_set = set(tags)
        for r in rows:
            r_tags = set(json.loads(r["tags"]) if r["tags"] else [])
            if tag_set & r_tags:
                results.append(self._row_to_dict(r))
                if len(results) >= limit:
                    break
        return results

    def recall_recent(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM episodic_memory ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_confidence(self, entry_id: int, confidence: float) -> dict:
        self._conn.execute(
            "UPDATE episodic_memory SET confidence=? WHERE id=?",
            (confidence, entry_id),
        )
        self._conn.commit()
        return {"entry_id": entry_id, "confidence": confidence}

    def forget_low_importance(self, threshold: float = 0.2) -> dict:
        cur = self._conn.execute(
            "DELETE FROM episodic_memory WHERE importance < ?", (threshold,)
        )
        self._conn.commit()
        return {"forgotten": cur.rowcount, "threshold": threshold}

    def summary(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM episodic_memory").fetchone()["c"]
        avg_imp = self._conn.execute("SELECT AVG(importance) as a FROM episodic_memory").fetchone()["a"] or 0
        avg_conf = self._conn.execute("SELECT AVG(confidence) as a FROM episodic_memory").fetchone()["a"] or 0
        return {"total_entries": total, "avg_importance": round(avg_imp, 3),
                "avg_confidence": round(avg_conf, 3)}

    def doctor(self) -> dict:
        return self.summary()

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
        return d
