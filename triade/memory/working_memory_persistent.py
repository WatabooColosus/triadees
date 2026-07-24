"""Working Memory Persistente: backup SQLite de la working memory RAM.

Wraps la WorkingMemory existente (RAM) y persiste items en SQLite
para sobrevivir reinicios. Mantiene la misma interfaz push/peek/get_context.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class PersistentWorkingItem:
    text: str = ""
    source: str = ""
    relevance: float = 0.5
    emotional_valence: float = 0.0
    urgency: float = 0.0
    novelty: float = 0.5
    confidence: float = 0.5
    timestamp: str = field(default_factory=utc_now)
    access_count: int = 0
    item_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text, "source": self.source,
            "relevance": round(self.relevance, 4),
            "emotional_valence": round(self.emotional_valence, 4),
            "urgency": round(self.urgency, 4), "novelty": round(self.novelty, 4),
            "confidence": round(self.confidence, 4),
            "timestamp": self.timestamp, "access_count": self.access_count,
            "item_id": self.item_id,
        }


class WorkingMemoryPersistent:
    """Working memory con backup SQLite. Mantiene interfaz compatible con WorkingMemory."""

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        max_size: int = 50,
    ) -> None:
        self.db_path = Path(db_path)
        self.max_size = max_size
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def push(
        self,
        *,
        text: str,
        source: str = "",
        relevance: float = 0.5,
        emotional_valence: float = 0.0,
        urgency: float = 0.0,
        novelty: float = 0.5,
        confidence: float = 0.5,
    ) -> PersistentWorkingItem:
        import uuid
        item_id = f"ww-{uuid.uuid4().hex[:8]}"
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO working_memory_persistent
                (item_id, text, source, relevance, emotional_valence, urgency, novelty, confidence, timestamp, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (item_id, text, source, max(0, min(1, relevance)),
                 max(-1, min(1, emotional_valence)), max(0, min(1, urgency)),
                 max(0, min(1, novelty)), max(0, min(1, confidence)), now),
            )
            self._prune(conn)
        return PersistentWorkingItem(
            text=text, source=source, relevance=relevance,
            emotional_valence=emotional_valence, urgency=urgency,
            novelty=novelty, confidence=confidence, timestamp=now, item_id=item_id,
        )

    def peek(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM working_memory_persistent
                ORDER BY (relevance * 0.4 + novelty * 0.25 + urgency * 0.2 + confidence * 0.15) DESC
                LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_context(self, limit: int = 10) -> str:
        items = self.peek(limit=limit)
        return "\n".join(f"[{i.get('source', '?')}] {i.get('text', '')}" for i in items)

    def touch(self, item_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE working_memory_persistent SET access_count = access_count + 1 WHERE item_id = ?",
                (item_id,),
            )

    def clear(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM working_memory_persistent")
            return cursor.rowcount

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) as c FROM working_memory_persistent").fetchone()["c"]

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM working_memory_persistent ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _prune(self, conn: sqlite3.Connection) -> None:
        count = conn.execute("SELECT COUNT(*) as c FROM working_memory_persistent").fetchone()["c"]
        if count > self.max_size:
            excess = count - self.max_size
            conn.execute(
                """DELETE FROM working_memory_persistent WHERE item_id IN
                (SELECT item_id FROM working_memory_persistent
                ORDER BY (relevance * 0.3 + urgency * 0.2 + confidence * 0.2 - novelty * 0.1 - access_count * 0.01) ASC
                LIMIT ?)""",
                (excess,),
            )

    def doctor(self) -> dict[str, Any]:
        count = self.count()
        with self._connect() as conn:
            avg_rel = conn.execute("SELECT AVG(relevance) as a FROM working_memory_persistent").fetchone()
        return {
            "count": count,
            "max_size": self.max_size,
            "utilization": round(count / max(1, self.max_size) * 100, 1),
            "avg_relevance": round(float(avg_rel["a"] or 0), 4),
        }
