"""Cola autónoma con lease atómico, idempotencia y recuperación."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ACTIVE = {"pending", "leased", "running", "retry_wait", "recovered"}
TERMINAL = {"completed", "failed", "dead_letter", "cancelled"}
ALL_STATES = ACTIVE | TERMINAL


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


class AutonomousTaskStore:
    """Persistencia separada de la cola legacy; nunca reclama con SELECT+UPDATE."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/009_runtime_resilience.sql"
        )
        with self._connect() as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @staticmethod
    def payload_hash(payload: dict[str, Any]) -> str:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return hashlib.sha256(raw).hexdigest()

    def enqueue(
        self,
        task_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        priority: int = 50,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key_required")
        now = _iso()
        task_id = f"task-{uuid4().hex}"
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM autonomous_tasks WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return self._decode(existing)
            conn.execute(
                """INSERT INTO autonomous_tasks
                (task_id,task_type,idempotency_key,status,priority,created_at,updated_at,max_attempts,payload_json,payload_hash)
                VALUES(?,?,?,'pending',?,?,?,?,?,?)""",
                (
                    task_id,
                    task_type,
                    idempotency_key,
                    int(priority),
                    now,
                    now,
                    max(1, int(max_attempts)),
                    canonical,
                    self.payload_hash(payload),
                ),
            )
            conn.commit()
        return self.get(task_id) or {}

    def claim(
        self, worker_id: str, *, lease_seconds: int = 60
    ) -> dict[str, Any] | None:
        if not worker_id.strip():
            raise ValueError("worker_id_required")
        now = _now()
        expires = _iso(now + timedelta(seconds=max(1, lease_seconds)))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT task_id FROM autonomous_tasks
                WHERE (status IN ('pending','recovered') OR (status='retry_wait' AND retry_after<=?))
                AND attempt < max_attempts
                ORDER BY priority ASC, created_at ASC LIMIT 1""",
                (_iso(now),),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            changed = conn.execute(
                """UPDATE autonomous_tasks SET status='leased',worker_id=?,lease_acquired_at=?,
                lease_expires_at=?,heartbeat_at=?,attempt=attempt+1,updated_at=?
                WHERE task_id=? AND status IN ('pending','recovered','retry_wait')""",
                (worker_id, _iso(now), expires, _iso(now), _iso(now), row["task_id"]),
            ).rowcount
            conn.commit()
        return self.get(str(row["task_id"])) if changed == 1 else None

    def start(self, task_id: str, worker_id: str) -> bool:
        return self._owned_update(
            task_id,
            worker_id,
            "status='running',heartbeat_at=?,updated_at=?",
            (_iso(), _iso()),
        )

    def claim_task(
        self, task_id: str, worker_id: str, *, lease_seconds: int = 60
    ) -> dict[str, Any] | None:
        """Reclama una tarea concreta de forma atómica para migración legacy."""
        if not task_id.strip() or not worker_id.strip():
            raise ValueError("task_id_and_worker_id_required")
        now = _now()
        now_iso = _iso(now)
        expires = _iso(now + timedelta(seconds=max(1, lease_seconds)))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                """UPDATE autonomous_tasks SET status='leased',worker_id=?,lease_acquired_at=?,
                lease_expires_at=?,heartbeat_at=?,attempt=attempt+1,updated_at=?
                WHERE task_id=?
                  AND (status IN ('pending','recovered') OR (status='retry_wait' AND retry_after<=?))
                  AND attempt < max_attempts""",
                (worker_id, now_iso, expires, now_iso, now_iso, task_id, now_iso),
            ).rowcount
            conn.commit()
        return self.get(task_id) if changed == 1 else None

    def renew(self, task_id: str, worker_id: str, *, lease_seconds: int = 60) -> bool:
        now = _now()
        return self._owned_update(
            task_id,
            worker_id,
            "lease_expires_at=?,heartbeat_at=?,updated_at=?",
            (
                _iso(now + timedelta(seconds=max(1, lease_seconds))),
                _iso(now),
                _iso(now),
            ),
        )

    def complete(self, task_id: str, worker_id: str, result_ref: str) -> bool:
        return self._owned_update(
            task_id,
            worker_id,
            "status='completed',result_ref=?,lease_expires_at=NULL,updated_at=?",
            (result_ref, _iso()),
        )

    def fail(
        self, task_id: str, worker_id: str, error: str, *, base_delay_seconds: int = 30
    ) -> dict[str, Any]:
        task = self.get(task_id)
        if not task or task.get("worker_id") != worker_id:
            return {"status": "not_owner"}
        dead = int(task["attempt"]) >= int(task["max_attempts"])
        status = "dead_letter" if dead else "retry_wait"
        retry = (
            None
            if dead
            else _iso(
                _now()
                + timedelta(
                    seconds=base_delay_seconds * (2 ** max(0, int(task["attempt"]) - 1))
                )
            )
        )
        self._owned_update(
            task_id,
            worker_id,
            "status=?,retry_after=?,last_error=?,lease_expires_at=NULL,updated_at=?",
            (status, retry, error[:2000], _iso()),
        )
        return self.get(task_id) or {}

    def recover_expired(self) -> list[str]:
        now = _iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT task_id FROM autonomous_tasks WHERE status IN ('leased','running') AND lease_expires_at<=?",
                (now,),
            ).fetchall()
            ids = [str(row["task_id"]) for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                conn.execute(
                    f"""UPDATE autonomous_tasks SET status='recovered',worker_id=NULL,lease_acquired_at=NULL,
                    lease_expires_at=NULL,heartbeat_at=NULL,last_error='expired_lease_recovered',updated_at=?
                    WHERE task_id IN ({placeholders})""",
                    (now, *ids),
                )
            conn.commit()
        return ids

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM autonomous_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        return self._decode(row) if row else None

    def _owned_update(
        self, task_id: str, worker_id: str, assignment: str, values: tuple[Any, ...]
    ) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                f"UPDATE autonomous_tasks SET {assignment} WHERE task_id=? AND worker_id=? AND status IN ('leased','running')",
                (*values, task_id, worker_id),
            ).rowcount
        return changed == 1

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item
