"""Cola autónoma con lease atómico, idempotencia y recuperación."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

ACTIVE = {"pending", "queued", "leased", "running", "retry_wait", "recovered", "deferred"}
TERMINAL_SUCCESS = {"completed"}
TERMINAL_NON_SUCCESS = {"blocked", "skipped", "dry_run", "observed", "cancelled"}
TERMINAL_FAILURE = {"failed", "dead_letter", "timeout", "lease_lost"}
TERMINAL = TERMINAL_SUCCESS | TERMINAL_NON_SUCCESS | TERMINAL_FAILURE
ALL_STATES = ACTIVE | TERMINAL


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


class AutonomousTaskStore:
    """Persistencia separada de la cola legacy; nunca reclama con SELECT+UPDATE."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        migrations = [
            Path(__file__).resolve().parents[1]
            / "memory/migrations/009_runtime_resilience.sql",
            Path(__file__).resolve().parents[1]
            / "memory/migrations/012_truthful_task_states.sql",
            Path(__file__).resolve().parents[1]
            / "memory/migrations/013_lease_fencing.sql",
        ]
        with self._connect() as conn:
            for migration in migrations:
                conn.executescript(migration.read_text(encoding="utf-8"))
            self._ensure_fencing_columns(conn)

    @staticmethod
    def _ensure_fencing_columns(conn: sqlite3.Connection) -> None:
        task_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(autonomous_tasks)")
        }
        if "lease_generation" not in task_columns:
            conn.execute(
                "ALTER TABLE autonomous_tasks ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0"
            )
        transition_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(autonomous_task_transitions)")
        }
        if "lease_generation" not in transition_columns:
            conn.execute(
                "ALTER TABLE autonomous_task_transitions ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0"
            )

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
                WHERE (status IN ('pending','queued','recovered')
                    OR (status IN ('retry_wait','deferred') AND retry_after<=?))
                AND attempt < max_attempts
                ORDER BY priority ASC, created_at ASC LIMIT 1""",
                (_iso(now),),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            changed = conn.execute(
                """UPDATE autonomous_tasks SET status='leased',worker_id=?,lease_acquired_at=?,
                lease_expires_at=?,heartbeat_at=?,attempt=attempt+1,updated_at=?,
                lease_generation=lease_generation+1
                WHERE task_id=? AND status IN ('pending','queued','recovered','retry_wait','deferred')""",
                (worker_id, _iso(now), expires, _iso(now), _iso(now), row["task_id"]),
            ).rowcount
            conn.commit()
        return self.get(str(row["task_id"])) if changed == 1 else None

    def start(self, task_id: str, worker_id: str, lease_generation: int) -> bool:
        return self._owned_update(
            task_id,
            worker_id,
            lease_generation,
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
                lease_expires_at=?,heartbeat_at=?,attempt=attempt+1,updated_at=?,
                lease_generation=lease_generation+1
                WHERE task_id=?
                  AND (status IN ('pending','queued','recovered')
                    OR (status IN ('retry_wait','deferred') AND retry_after<=?))
                  AND attempt < max_attempts""",
                (worker_id, now_iso, expires, now_iso, now_iso, task_id, now_iso),
            ).rowcount
            conn.commit()
        return self.get(task_id) if changed == 1 else None

    def renew(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        *,
        lease_seconds: int = 60,
    ) -> bool:
        now = _now()
        renewed = self._owned_update(
            task_id,
            worker_id,
            lease_generation,
            "lease_expires_at=?,heartbeat_at=?,updated_at=?",
            (
                _iso(now + timedelta(seconds=max(1, lease_seconds))),
                _iso(now),
                _iso(now),
            ),
        )
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO autonomous_lease_heartbeats
                (task_id,worker_id,lease_generation,renewed,created_at) VALUES(?,?,?,?,?)""",
                (task_id, worker_id, lease_generation, int(renewed), _iso(now)),
            )
        return renewed

    def complete(
        self, task_id: str, worker_id: str, lease_generation: int, result_ref: str
    ) -> bool:
        if not result_ref.strip():
            raise ValueError("completed_requires_result_ref")
        if not Path(result_ref).is_file():
            return False
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "completed", result_ref=result_ref
        )

    def block(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "blocked", reason=reason
        )

    def skip(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "skipped", reason=reason
        )

    def mark_dry_run(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "dry_run", reason=reason
        )

    def cancel(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "cancelled", reason=reason
        )

    def mark_observed(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "observed", reason=reason
        )

    def mark_timeout(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        reason: str,
        *,
        retryable: bool = True,
    ) -> bool:
        if retryable:
            outcome = self.fail(
                task_id, worker_id, lease_generation, f"timeout:{reason}"
            )
            return outcome.get("status") in {"retry_wait", "dead_letter"}
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "timeout", reason=reason
        )

    def mark_lease_lost(
        self, task_id: str, worker_id: str, lease_generation: int, reason: str
    ) -> bool:
        return self._terminal_transition(
            task_id, worker_id, lease_generation, "lease_lost", reason=reason
        )

    def defer(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        reason: str,
        *,
        delay_seconds: int = 30,
    ) -> bool:
        retry_after = _iso(_now() + timedelta(seconds=max(0, delay_seconds)))
        return self._transition(
            task_id,
            worker_id,
            lease_generation,
            "deferred",
            reason=reason,
            retry_after=retry_after,
        )

    def fail(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        error: str,
        *,
        base_delay_seconds: int = 30,
    ) -> dict[str, Any]:
        task = self.get(task_id)
        if (
            not task
            or task.get("worker_id") != worker_id
            or int(task.get("lease_generation") or -1) != lease_generation
        ):
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
        transitioned = self._transition(
            task_id,
            worker_id,
            lease_generation,
            status,
            reason=error[:2000],
            retry_after=retry,
        )
        if not transitioned:
            return {"status": "not_owner"}
        return self.get(task_id) or {}

    def _terminal_transition(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        status: str,
        *,
        reason: str | None = None,
        result_ref: str | None = None,
    ) -> bool:
        if status not in TERMINAL:
            raise ValueError(f"unknown_terminal_status:{status}")
        return self._transition(
            task_id,
            worker_id,
            lease_generation,
            status,
            reason=reason,
            result_ref=result_ref,
        )

    def _transition(
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        status: str,
        *,
        reason: str | None = None,
        result_ref: str | None = None,
        retry_after: str | None = None,
    ) -> bool:
        if status not in ALL_STATES:
            raise ValueError(f"unknown_status:{status}")
        now = _iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute(
                """SELECT status FROM autonomous_tasks
                WHERE task_id=? AND worker_id=? AND lease_generation=?""",
                (task_id, worker_id, lease_generation),
            ).fetchone()
            if current is None or str(current["status"]) not in {"leased", "running"}:
                conn.commit()
                return False
            previous = str(current["status"])
            changed = conn.execute(
                """UPDATE autonomous_tasks SET status=?,retry_after=?,last_error=?,result_ref=?,
                lease_expires_at=NULL,updated_at=? WHERE task_id=? AND worker_id=?
                AND lease_generation=? AND status IN ('leased','running')""",
                (
                    status,
                    retry_after,
                    reason,
                    result_ref,
                    now,
                    task_id,
                    worker_id,
                    lease_generation,
                ),
            ).rowcount
            if changed == 1:
                conn.execute(
                    """INSERT INTO autonomous_task_transitions
                    (task_id,worker_id,lease_generation,from_status,to_status,reason,result_ref,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        task_id,
                        worker_id,
                        lease_generation,
                        previous,
                        status,
                        reason,
                        result_ref,
                        now,
                    ),
                )
            conn.commit()
        return changed == 1

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
        self,
        task_id: str,
        worker_id: str,
        lease_generation: int,
        assignment: str,
        values: tuple[Any, ...],
    ) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                f"UPDATE autonomous_tasks SET {assignment} WHERE task_id=? AND worker_id=? AND lease_generation=? AND status IN ('leased','running')",
                (*values, task_id, worker_id, lease_generation),
            ).rowcount
        return changed == 1

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json") or "{}")
        return item
