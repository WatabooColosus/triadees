"""Recuperación conservadora y auditable, sin shell ni systemctl embebido."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.runtime.task_leases import AutonomousTaskStore


class RuntimeRecovery:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        snapshot_dir: str | Path = "artifacts/recovery",
    ) -> None:
        self.db_path = Path(db_path)
        self.snapshot_dir = Path(snapshot_dir)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.tasks = AutonomousTaskStore(self.db_path)

    def recover(
        self,
        cause: str,
        *,
        stop_workers: Callable[[], Any] | None = None,
        start_workers: Callable[[], Any] | None = None,
        verify_heartbeat: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        recovery_id = f"recovery-{uuid4().hex[:16]}"
        created = datetime.now(UTC).isoformat()
        actions: list[dict[str, Any]] = []
        snapshot = self._snapshot(recovery_id)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO runtime_recovery_events
                (recovery_id,cause,state,snapshot_ref,actions_json,created_at) VALUES(?,?,'recovering',?,? ,?)""",
                (recovery_id, cause, snapshot, "[]", created),
            )
        try:
            if stop_workers:
                actions.append({"action": "stop_workers", "result": stop_workers()})
            recovered = self.tasks.recover_expired()
            actions.append({"action": "recover_expired_leases", "task_ids": recovered})
            with sqlite3.connect(self.db_path, timeout=5) as conn:
                integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
            actions.append({"action": "sqlite_quick_check", "result": integrity})
            if integrity != "ok":
                raise RuntimeError("sqlite_quick_check_failed")
            if start_workers:
                actions.append({"action": "start_workers", "result": start_workers()})
            heartbeat_ok = verify_heartbeat() if verify_heartbeat else True
            actions.append({"action": "verify_heartbeat", "result": bool(heartbeat_ok)})
            if not heartbeat_ok:
                raise RuntimeError("new_heartbeat_not_observed")
            state, error = "runtime_recovered", None
        except Exception as exc:
            state, error = "critical", f"{type(exc).__name__}: {exc}"
        finished = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE runtime_recovery_events SET state=?,actions_json=?,error=?,finished_at=? WHERE recovery_id=?",
                (
                    state,
                    json.dumps(actions, ensure_ascii=False, default=str),
                    error,
                    finished,
                    recovery_id,
                ),
            )
        return {
            "recovery_id": recovery_id,
            "state": state,
            "snapshot_ref": snapshot,
            "actions": actions,
            "error": error,
            "rollback": {"database_snapshot": snapshot},
        }

    def _snapshot(self, recovery_id: str) -> str:
        output = self.snapshot_dir / f"{recovery_id}.db"
        with sqlite3.connect(self.db_path) as source, sqlite3.connect(output) as target:
            source.backup(target)
        return str(output)
