"""Audited, reversible compatibility switch for the retired legacy queue."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.db import sqlite3


class LegacyCompatibilityController:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        from triade.runtime.task_leases import AutonomousTaskStore

        AutonomousTaskStore(self.db_path)
        migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/019_legacy_retirement.sql"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))

    def status(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM runtime_queue_compatibility WHERE singleton=1"
            ).fetchone()
        if row is None:
            raise RuntimeError("runtime_queue_compatibility_missing")
        return dict(row)

    def set_compatibility(
        self, *, enabled: bool, actor: str, reason: str
    ) -> dict[str, Any]:
        clean_actor = actor.strip()
        clean_reason = reason.strip()
        if not clean_actor or not clean_reason:
            raise ValueError("actor_and_reason_required")
        current = self.status()
        mode = "legacy_compatibility" if enabled else "v2_canonical"
        now = utc_now()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE runtime_queue_compatibility
                SET mode=?,legacy_writes_enabled=?,updated_at=?,updated_by=?,rollback_reason=?
                WHERE singleton=1""",
                (
                    mode,
                    int(enabled),
                    now,
                    clean_actor,
                    clean_reason if enabled else None,
                ),
            )
            conn.execute(
                """INSERT INTO runtime_queue_compatibility_events
                (from_mode,to_mode,legacy_writes_enabled,actor,reason,created_at)
                VALUES(?,?,?,?,?,?)""",
                (
                    current["mode"],
                    mode,
                    int(enabled),
                    clean_actor,
                    clean_reason,
                    now,
                ),
            )
        return self.status()

    def metrics(self) -> dict[str, int | str]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            legacy_total = int(
                conn.execute("SELECT COUNT(*) FROM worker_tasks").fetchone()[0]
            )
            linked = int(
                conn.execute(
                    "SELECT COUNT(*) FROM worker_tasks WHERE autonomous_task_id IS NOT NULL"
                ).fetchone()[0]
            )
            pending = int(
                conn.execute(
                    """SELECT COUNT(*) FROM worker_tasks
                    WHERE migration_status IN ('pending','delegating','delegated','migration_error')"""
                ).fetchone()[0]
            )
            v2_total = int(
                conn.execute("SELECT COUNT(*) FROM autonomous_tasks").fetchone()[0]
            )
            duplicate_links = int(
                conn.execute(
                    """SELECT COUNT(*) FROM (
                    SELECT autonomous_task_id FROM worker_tasks
                    WHERE autonomous_task_id IS NOT NULL
                    GROUP BY autonomous_task_id HAVING COUNT(*) > 1)"""
                ).fetchone()[0]
            )
            compatibility_events = int(
                conn.execute(
                    "SELECT COUNT(*) FROM runtime_queue_compatibility_events"
                ).fetchone()[0]
            )
        status = self.status()
        return {
            "mode": str(status["mode"]),
            "legacy_total": legacy_total,
            "legacy_linked": linked,
            "legacy_pending_reconciliation": pending,
            "v2_total": v2_total,
            "duplicate_links": duplicate_links,
            "compatibility_events": compatibility_events,
        }
