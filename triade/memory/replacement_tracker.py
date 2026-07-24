"""Replacement Tracker: tracking de reemplazos de memoria.

Registra qué conocimiento reemplaza a qué, cuándo y por qué.
Permite auditar la evolución del conocimiento y revertir si es necesario.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class ReplacementRecord:
    record_id: str = ""
    replaced_id: str = ""
    replacement_id: str = ""
    reason: str = ""
    domain: str = ""
    confidence_before: float = 0.0
    confidence_after: float = 0.0
    reversible: bool = True
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id, "replaced_id": self.replaced_id,
            "replacement_id": self.replacement_id, "reason": self.reason,
            "domain": self.domain, "confidence_before": round(self.confidence_before, 4),
            "confidence_after": round(self.confidence_after, 4),
            "reversible": self.reversible, "created_at": self.created_at,
        }


class ReplacementTracker:
    """Trackea reemplazos de conocimiento en memoria."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def record_replacement(
        self,
        *,
        replaced_id: str,
        replacement_id: str,
        reason: str = "",
        domain: str = "",
        confidence_before: float = 0.0,
        confidence_after: float = 0.0,
        reversible: bool = True,
    ) -> ReplacementRecord:
        import uuid
        record_id = f"repl-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO memory_replacements
                (record_id, replaced_id, replacement_id, reason, domain,
                 confidence_before, confidence_after, reversible, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record_id, replaced_id, replacement_id, reason, domain,
                 confidence_before, confidence_after, reversible, now),
            )
        return ReplacementRecord(
            record_id=record_id, replaced_id=replaced_id,
            replacement_id=replacement_id, reason=reason, domain=domain,
            confidence_before=confidence_before, confidence_after=confidence_after,
            reversible=reversible, created_at=now,
        )

    def get_replacements_for(self, item_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_replacements
                WHERE replaced_id = ? OR replacement_id = ?
                ORDER BY created_at DESC""",
                (item_id, item_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_replacement_chain(self, item_id: str, max_depth: int = 10) -> list[dict[str, Any]]:
        """Sigue la cadena de reemplazos desde un item hasta la raíz."""
        chain: list[dict[str, Any]] = []
        current = item_id
        visited: set[str] = set()
        for _ in range(max_depth):
            if current in visited:
                break
            visited.add(current)
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM memory_replacements WHERE replacement_id = ? LIMIT 1",
                    (current,),
                ).fetchone()
                if row is None:
                    break
                chain.append(dict(row))
                current = str(row["replaced_id"])
        return chain

    def reversible_replacements(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_replacements WHERE reversible = 1 ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as c FROM memory_replacements").fetchone()["c"]
            by_domain = conn.execute(
                "SELECT domain, COUNT(*) as c FROM memory_replacements GROUP BY domain"
            ).fetchall()
            reversible = conn.execute(
                "SELECT COUNT(*) as c FROM memory_replacements WHERE reversible = 1"
            ).fetchone()["c"]
        return {
            "total_replacements": total,
            "by_domain": {r["domain"]: r["c"] for r in by_domain},
            "reversible": reversible,
        }
