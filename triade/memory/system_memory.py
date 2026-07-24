"""System Memory: estado del sistema unificado.

Consolida información dispersa (hardware, modelos, workers, scheduler)
en un único almacén de estado del sistema.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class SystemState:
    key: str = ""
    value: Any = None
    category: str = "general"
    source: str = ""
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "value": self.value, "category": self.category,
            "source": self.source, "updated_at": self.updated_at,
        }


class SystemMemory:
    """Almacén unificado de estado del sistema (key-value categorizado)."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def set(self, key: str, value: Any, *, category: str = "general", source: str = "") -> SystemState:
        now = utc_now()
        value_json = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
        with self._connect() as conn:
            existing = conn.execute("SELECT 1 FROM system_state WHERE key = ?", (key,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE system_state SET value = ?, category = ?, source = ?, updated_at = ? WHERE key = ?",
                    (value_json, category, source, now, key),
                )
            else:
                conn.execute(
                    "INSERT INTO system_state (key, value, category, source, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (key, value_json, category, source, now),
                )
        return SystemState(key=key, value=value, category=category, source=source, updated_at=now)

    def get(self, key: str, default: Any = None) -> Any:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM system_state WHERE key = ?", (key,)).fetchone()
            if row is None:
                return default
            raw = row["value"]
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return raw

    def get_by_category(self, category: str) -> list[SystemState]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM system_state WHERE category = ? ORDER BY updated_at DESC", (category,)
            ).fetchall()
        return [self._row_to_state(r) for r in rows]

    def delete(self, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM system_state WHERE key = ?", (key,))
            return cursor.rowcount > 0

    def list_keys(self, category: str | None = None, limit: int = 100) -> list[str]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT key FROM system_state WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key FROM system_state ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [r["key"] for r in rows]

    def snapshot(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value, category FROM system_state ORDER BY key").fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            key = str(row["key"])
            raw = row["value"]
            try:
                result[key] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                result[key] = raw
        return result

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) as c FROM system_state").fetchone()["c"]
            cats = conn.execute(
                "SELECT category, COUNT(*) as c FROM system_state GROUP BY category"
            ).fetchall()
        return {"total_keys": count, "by_category": {r["category"]: r["c"] for r in cats}}

    @staticmethod
    def _row_to_state(row: sqlite3.Row) -> SystemState:
        raw = row["value"]
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            value = raw
        return SystemState(
            key=str(row["key"]), value=value,
            category=str(row["category"] or "general"),
            source=str(row["source"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )
