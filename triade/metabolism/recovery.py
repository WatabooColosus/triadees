from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.db import sqlite3

logger = logging.getLogger(__name__)


class RecoveryManager:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def recover_interrupted_cycles(self) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.row_factory = sqlite3.Row
                orphans = conn.execute(
                    """SELECT * FROM metabolic_cycle
                    WHERE status IN ('running','starting') AND finished_at IS NULL"""
                ).fetchall()
                for row in orphans:
                    cycle = dict(row)
                    self._mark_cycle_interrupted(conn, cycle["cycle_id"])
                    self._recover_needs(conn, cycle["cycle_id"])
                    recovered.append(cycle)
        except (sqlite3.Error, OSError) as exc:
            logger.warning("recover_interrupted_cycles_failed: %s", exc)
        return recovered

    def _mark_cycle_interrupted(self, conn: sqlite3.Connection, cycle_id: int) -> None:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """UPDATE metabolic_cycle
            SET status='interrupted', finished_at=?, error='recovered_after_interruption'
            WHERE cycle_id=?""",
            (now, cycle_id),
        )

    def _recover_needs(self, conn: sqlite3.Connection, cycle_id: int) -> None:
        running = conn.execute(
            """SELECT need_id FROM metabolic_needs
            WHERE cycle_id=? AND status='running'""",
            (cycle_id,),
        ).fetchall()
        for (need_id,) in running:
            conn.execute(
                "UPDATE metabolic_needs SET status='recovered' WHERE need_id=?",
                (need_id,),
            )

    def needs_after_recovery(self) -> list[dict[str, Any]]:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT * FROM metabolic_needs
                    WHERE status IN ('pending','recovered')
                    ORDER BY priority DESC LIMIT 10"""
                ).fetchall()
                return [dict(r) for r in rows]
        except (sqlite3.Error, OSError) as exc:
            logger.warning("needs_after_recovery_failed: %s", exc)
            return []
