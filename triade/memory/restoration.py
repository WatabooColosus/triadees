"""Restoration: restauración de memoria olvidada y des-cuarentena.

Permite recuperar memorias que fueron olvidadas o puestas en cuarentena
cuando nuevas evidencias las respaldan.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class RestorationResult:
    operation: str = ""
    items_restored: int = 0
    items_derequarantined: int = 0
    details: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation, "items_restored": self.items_restored,
            "items_derequarantined": self.items_derequarantined,
            "details": list(self.details), "created_at": self.created_at,
        }


class MemoryRestorer:
    """Restaura memoria olvidada o en cuarentena."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def derequarantine(
        self,
        *,
        min_confidence: float = 0.6,
    ) -> RestorationResult:
        """Saca de cuarentena memorias con suficiente confianza."""
        restored = 0
        details: list[str] = []
        with self._connect() as conn:
            quarantined = conn.execute(
                """SELECT id, value, confidence
                FROM semantic_memory
                WHERE status = 'quarantined'"""
            ).fetchall()
            for row in quarantined:
                conf = float(row["confidence"] or 0)
                if conf >= min_confidence:
                    conn.execute(
                        "UPDATE semantic_memory SET status = 'stable' WHERE id = ?",
                        (row["id"],),
                    )
                    restored += 1
                    details.append(f"ID {row['id']}: conf={conf:.2f} -> stable")
        return RestorationResult(
            operation="derequarantine", items_restored=restored, details=details,
        )

    def restore_forgotten(
        self,
        *,
        domain: str = "",
        min_confidence: float = 0.5,
        max_items: int = 20,
    ) -> RestorationResult:
        """Restaura memorias olvidadas de un dominio específico."""
        restored = 0
        details: list[str] = []
        with self._connect() as conn:
            if domain:
                forgotten = conn.execute(
                    """SELECT id, value, confidence, domain
                    FROM semantic_memory
                    WHERE domain = ? AND confidence < ? AND status != 'stable'
                    ORDER BY confidence DESC LIMIT ?""",
                    (domain, min_confidence, max_items),
                ).fetchall()
            else:
                forgotten = conn.execute(
                    """SELECT id, value, confidence, domain
                    FROM semantic_memory
                    WHERE confidence < ? AND status != 'stable'
                    ORDER BY confidence DESC LIMIT ?""",
                    (min_confidence, max_items),
                ).fetchall()
            for row in forgotten:
                new_conf = min(1.0, float(row["confidence"] or 0) + 0.1)
                conn.execute(
                    "UPDATE semantic_memory SET confidence = ? WHERE id = ?",
                    (round(new_conf, 4), row["id"]),
                )
                restored += 1
                details.append(f"ID {row['id']}: conf {float(row['confidence']):.2f} -> {new_conf:.2f}")
        return RestorationResult(
            operation="restore_forgotten", items_restored=restored, details=details,
        )

    def promote_candidates(
        self,
        *,
        min_confidence: float = 0.7,
        min_run_use: int = 3,
    ) -> RestorationResult:
        """Promueve candidatos con suficiente confianza y uso a 'unverified'."""
        promoted = 0
        details: list[str] = []
        with self._connect() as conn:
            candidates = conn.execute(
                """SELECT id, content, confidence
                FROM learning_queue
                WHERE status = 'candidate' AND confidence >= ?""",
                (min_confidence,),
            ).fetchall()
            for row in candidates:
                promoted += 1
                conn.execute(
                    "UPDATE learning_queue SET status = 'evaluated' WHERE id = ?",
                    (row["id"],),
                )
                details.append(f"ID {row['id']}: candidate -> evaluated (conf={float(row['confidence']):.2f})")
        return RestorationResult(
            operation="promote_candidates", items_restored=promoted, details=details,
        )

    def summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            quarantined = conn.execute(
                "SELECT COUNT(*) as c FROM semantic_memory WHERE status = 'quarantined'"
            ).fetchone()["c"]
            candidates = conn.execute(
                "SELECT COUNT(*) as c FROM learning_queue WHERE status = 'candidate'"
            ).fetchone()["c"]
            low_conf = conn.execute(
                "SELECT COUNT(*) as c FROM semantic_memory WHERE confidence < 0.5"
            ).fetchone()["c"]
        return {
            "quarantined": quarantined,
            "pending_candidates": candidates,
            "low_confidence": low_conf,
        }
