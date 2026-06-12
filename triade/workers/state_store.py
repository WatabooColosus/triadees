"""Persistencia SQLite para Triade Living Workers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.core.error_bus import prune_worker_events
from .contracts import WorkerRunConfig, WorkerTask


class WorkerStateStore:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        repo_root = Path(__file__).resolve().parents[2]
        self.schema_path = repo_root / "triade/memory/schemas.sql"
        self.migration_path = repo_root / "triade/memory/migrations/003_living_workers.sql"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(f"No existe el esquema de memoria: {self.schema_path}")
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))
            if self.migration_path.exists():
                conn.executescript(self.migration_path.read_text(encoding="utf-8"))

    def create_worker_run(self, run_ref: str, config: WorkerRunConfig, artifact_dir: str | Path) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO worker_runs
                (run_ref, status, mode, dry_run, max_iterations, sleep_seconds, started_at, artifact_dir, summary_json)
                VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_ref,
                    "daemon" if config.daemon else "once",
                    1 if config.dry_run else 0,
                    config.max_iterations,
                    config.sleep_seconds,
                    utc_now(),
                    str(artifact_dir),
                    json.dumps({"iterations": 0}, ensure_ascii=False),
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO runs (run_id, source, user_input, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (run_ref, "worker", "Triade Living Workers background cycle", "created", utc_now()),
            )
        return self.get_worker_run(run_ref) or {}

    def finish_worker_run(self, run_ref: str, status: str, summary: dict[str, Any], error: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE worker_runs SET status = ?, finished_at = ?, summary_json = ?, error = ? WHERE run_ref = ?",
                (status, utc_now(), json.dumps(summary, ensure_ascii=False), error, run_ref),
            )
            conn.execute("UPDATE runs SET status = ?, closed_at = ? WHERE run_id = ?", (status, utc_now(), run_ref))

    def get_worker_run(self, run_ref: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM worker_runs WHERE run_ref = ?", (run_ref,)).fetchone()
        return self._decode(row) if row else None

    def list_worker_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM worker_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(row) for row in rows]

    def enqueue_task(self, task_type: str, payload: dict[str, Any] | None = None, priority: int = 50, run_ref: str | None = None) -> WorkerTask:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO worker_tasks (task_type, status, priority, payload_json, created_at, run_ref)
                VALUES (?, 'pending', ?, ?, ?, ?)""",
                (task_type, int(priority), json.dumps(payload or {}, ensure_ascii=False), utc_now(), run_ref),
            )
            task_id = int(cursor.lastrowid)
        return self.get_task(task_id) or WorkerTask(id=task_id, task_type=task_type, payload=payload or {}, priority=priority)

    def claim_next_task(self) -> WorkerTask | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM worker_tasks WHERE status = 'pending' ORDER BY priority ASC, id ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE worker_tasks SET status = 'running', started_at = ? WHERE id = ?", (utc_now(), row["id"]))
        task = self.get_task(int(row["id"]))
        return task

    def get_task(self, task_id: int) -> WorkerTask | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM worker_tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status:
                rows = conn.execute("SELECT * FROM worker_tasks WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM worker_tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._task_from_row(row).to_dict() for row in rows]

    def finish_task(self, task_id: int, status: str, result: dict[str, Any] | None = None, safety_status: str | None = None, error: str | None = None, run_ref: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE worker_tasks SET status = ?, result_json = ?, safety_status = ?, finished_at = ?, error = ?, run_ref = COALESCE(?, run_ref)
                WHERE id = ?""",
                (status, json.dumps(result or {}, ensure_ascii=False), safety_status, utc_now(), error, run_ref, task_id),
            )

    def record_event(self, event_type: str, message: str, *, run_ref: str | None = None, task_id: int | None = None, task_type: str | None = None, status: str = "ok", payload: dict[str, Any] | None = None) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO worker_events (run_ref, task_id, task_type, event_type, status, message, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_ref, task_id, task_type, event_type, status, message, json.dumps(payload or {}, ensure_ascii=False), utc_now()),
            )
            prune_worker_events(conn)
            return int(cursor.lastrowid)

    def list_events(self, limit: int = 50, run_ref: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if run_ref:
                rows = conn.execute("SELECT * FROM worker_events WHERE run_ref = ? ORDER BY id DESC LIMIT ?", (run_ref, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM worker_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(row) for row in rows]

    def set_state(self, key: str, value: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO worker_state (key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at""",
                (key, json.dumps(value, ensure_ascii=False), utc_now()),
            )

    def get_state(self, key: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM worker_state WHERE key = ?", (key,)).fetchone()
        return self._decode(row).get("value_json") if row else None

    def status(self) -> dict[str, Any]:
        with self._connect() as conn:
            task_counts = {row["status"]: int(row["c"]) for row in conn.execute("SELECT status, COUNT(*) AS c FROM worker_tasks GROUP BY status").fetchall()}
            run_counts = {row["status"]: int(row["c"]) for row in conn.execute("SELECT status, COUNT(*) AS c FROM worker_runs GROUP BY status").fetchall()}
        return {
            "status": "ok",
            "mode": "triade-living-workers",
            "task_counts": task_counts,
            "run_counts": run_counts,
            "last_run": (self.list_worker_runs(limit=1) or [None])[0],
            "state": self.get_state("workers") or {},
        }

    def doctor(self) -> dict[str, Any]:
        status = self.status()
        status["policy"] = {
            "identity_core_modified": False,
            "stable_memory_auto_write": False,
            "external_network_by_default": False,
            "audit_artifacts": "runs/background/YYYYMMDD-HHMMSS/",
        }
        return status

    def _task_from_row(self, row: sqlite3.Row) -> WorkerTask:
        item = self._decode(row)
        return WorkerTask(
            id=int(item["id"]),
            task_type=str(item["task_type"]),
            payload=item.get("payload_json") or {},
            priority=int(item.get("priority") or 50),
            status=str(item.get("status") or "pending"),
            safety_status=item.get("safety_status"),
            run_ref=item.get("run_ref"),
            created_at=str(item.get("created_at") or ""),
            started_at=item.get("started_at"),
            finished_at=item.get("finished_at"),
            error=item.get("error"),
            result=item.get("result_json") or {},
        )

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        for key in ("payload_json", "result_json", "summary_json", "value_json"):
            if key in item:
                try:
                    item[key] = json.loads(item.get(key) or "{}")
                except (json.JSONDecodeError, TypeError):
                    item[key] = {}
        return item
