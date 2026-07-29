"""Repair legacy/v2 bridge drift without overriding v2 truth."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.runtime.task_leases import AutonomousTaskStore


class LegacyTaskReconciler:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def reconcile(self) -> dict[str, int]:
        AutonomousTaskStore(self.db_path)
        repaired = 0
        errors = 0
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT w.id,w.status AS legacy_status,w.autonomous_task_id,
                w.migration_status,a.status AS v2_status,a.result_ref
                FROM worker_tasks w LEFT JOIN autonomous_tasks a
                ON a.task_id=w.autonomous_task_id
                WHERE w.migration_status IN ('delegating','delegated','migration_error')"""
            ).fetchall()
            for row in rows:
                if not row["autonomous_task_id"] or row["v2_status"] is None:
                    conn.execute(
                        """UPDATE worker_tasks SET status='pending',migration_status='pending',
                        started_at=NULL,migration_error='missing_v2_link',reconciled_at=? WHERE id=?""",
                        (utc_now(), row["id"]),
                    )
                    repaired += 1
                    continue
                if row["legacy_status"] == "completed" and row["v2_status"] not in {
                    "completed",
                    "blocked",
                    "skipped",
                    "dry_run",
                    "observed",
                    "cancelled",
                    "failed",
                    "dead_letter",
                    "timeout",
                    "lease_lost",
                }:
                    conn.execute(
                        """UPDATE worker_tasks SET status='claimed',migration_status='delegated',
                        finished_at=NULL,migration_error='legacy_terminal_reverted_to_v2_truth',
                        reconciled_at=? WHERE id=?""",
                        (utc_now(), row["id"]),
                    )
                    repaired += 1
                    continue
                if row["v2_status"] in {
                    "completed",
                    "blocked",
                    "skipped",
                    "dry_run",
                    "observed",
                    "cancelled",
                    "failed",
                    "dead_letter",
                    "timeout",
                    "lease_lost",
                }:
                    result: dict[str, Any] = {
                        "autonomous_task_id": row["autonomous_task_id"]
                    }
                    ref = row["result_ref"]
                    if ref and Path(str(ref)).is_file():
                        try:
                            result = json.loads(
                                Path(str(ref)).read_text(encoding="utf-8")
                            )
                        except (OSError, ValueError):
                            errors += 1
                    migration = (
                        "mirrored_completed"
                        if row["v2_status"] == "completed"
                        else "mirrored_failed"
                    )
                    conn.execute(
                        """UPDATE worker_tasks SET status=?,result_json=?,finished_at=?,
                        migration_status=?,reconciled_at=?,migration_error=NULL WHERE id=?""",
                        (
                            row["v2_status"],
                            json.dumps(result, ensure_ascii=False),
                            utc_now(),
                            migration,
                            utc_now(),
                            row["id"],
                        ),
                    )
                    repaired += 1
        return {"repaired": repaired, "errors": errors}
