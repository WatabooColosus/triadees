"""Advanced Scheduler — live instance queries, leases, retry, backoff,
circuit breaker, PlanGraph dependencies, persistence.

Queries live instances (not creates new ones).
Leases prevent double-assignment.
Backoff: exponential on retry.
Circuit breaker: opens after consecutive failures.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now

log = logging.getLogger(__name__)


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{int(time.time() * 1000)}-{hashlib.md5(str(time.time()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scheduler_priorities (
    task_type      TEXT PRIMARY KEY,
    base_priority  INTEGER DEFAULT 10,
    current_priority INTEGER DEFAULT 10,
    decay_rate     REAL DEFAULT 0.05,
    updated_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scheduler_quotas (
    task_type      TEXT PRIMARY KEY,
    max_per_hour   INTEGER DEFAULT 100,
    max_per_day    INTEGER DEFAULT 1000,
    used_hour      INTEGER DEFAULT 0,
    used_day       INTEGER DEFAULT 0,
    hour_reset_at  TEXT,
    day_reset_at   TEXT
);
CREATE TABLE IF NOT EXISTS worker_heartbeats (
    worker_id      TEXT PRIMARY KEY,
    last_heartbeat TEXT NOT NULL,
    status         TEXT DEFAULT 'active',
    tasks_running  INTEGER DEFAULT 0,
    cpu_pct        REAL DEFAULT 0.0,
    mem_mb         REAL DEFAULT 0.0,
    metadata_json  TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS task_leases (
    lease_id       TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL,
    worker_id      TEXT NOT NULL,
    acquired_at    TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS tl_task ON task_leases(task_id);
CREATE INDEX IF NOT EXISTS tl_worker ON task_leases(worker_id);
CREATE INDEX IF NOT EXISTS tl_status ON task_leases(status);
CREATE TABLE IF NOT EXISTS circuit_breakers (
    breaker_id     TEXT PRIMARY KEY,
    component      TEXT NOT NULL,
    state          TEXT NOT NULL DEFAULT 'closed',
    failure_count  INTEGER DEFAULT 0,
    success_count  INTEGER DEFAULT 0,
    last_failure_at TEXT,
    last_success_at TEXT,
    opened_at      TEXT,
    threshold      INTEGER DEFAULT 5,
    reset_timeout  REAL DEFAULT 60.0
);
CREATE INDEX IF NOT EXISTS cb_component ON circuit_breakers(component);
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    dlq_id         TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL,
    task_type      TEXT NOT NULL,
    payload_json   TEXT DEFAULT '{}',
    failure_reason TEXT DEFAULT '',
    attempts       INTEGER DEFAULT 0,
    created_at     TEXT NOT NULL,
    resolved       INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scheduler_load_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    worker_count   INTEGER DEFAULT 0,
    tasks_queued   INTEGER DEFAULT 0,
    tasks_running  INTEGER DEFAULT 0,
    load_score     REAL DEFAULT 0.0,
    created_at     TEXT NOT NULL
);
"""


class CircuitBreaker:
    def __init__(self, component: str, threshold: int = 5, reset_timeout: float = 60.0,
                 conn: sqlite3.Connection | None = None):
        self.component = component
        self.threshold = threshold
        self.reset_timeout = reset_timeout
        self._conn = conn

    def _get_state(self) -> dict[str, Any]:
        if not self._conn:
            return {"state": "closed", "failure_count": 0}
        row = self._conn.execute(
            "SELECT * FROM circuit_breakers WHERE component=?", (self.component,)
        ).fetchone()
        if not row:
            return {"state": "closed", "failure_count": 0, "breaker_id": ""}
        d = dict(row)
        if d["state"] == "open" and d.get("opened_at"):
            try:
                opened_ts = datetime.fromisoformat(d["opened_at"]).timestamp()
                if time.time() - opened_ts > self.reset_timeout:
                    self._conn.execute(
                        "UPDATE circuit_breakers SET state='half_open' WHERE component=?",
                        (self.component,),
                    )
                    self._conn.commit()
                    d["state"] = "half_open"
            except Exception:
                pass
        return d

    @property
    def is_open(self) -> bool:
        return self._get_state()["state"] == "open"

    @property
    def allows_request(self) -> bool:
        state = self._get_state()
        return state["state"] in ("closed", "half_open")

    def record_success(self) -> None:
        if not self._conn:
            return
        now = utc_now()
        state = self._get_state()
        bid = state.get("breaker_id", "")
        if not bid:
            bid = _gen_id("cb")
            self._conn.execute(
                """INSERT INTO circuit_breakers
                   (breaker_id, component, state, success_count, last_success_at)
                   VALUES (?,?,?,?,?)""",
                (bid, self.component, "closed", 1, now),
            )
        else:
            new_count = state.get("success_count", 0) + 1
            new_state = "closed" if state["state"] == "half_open" and new_count >= 2 else state["state"]
            self._conn.execute(
                """UPDATE circuit_breakers
                   SET state=?, success_count=?, last_success_at=?
                   WHERE breaker_id=?""",
                (new_state, new_count, now, bid),
            )
        self._conn.commit()

    def record_failure(self) -> None:
        if not self._conn:
            return
        now = utc_now()
        state = self._get_state()
        bid = state.get("breaker_id", "")
        new_count = state.get("failure_count", 0) + 1
        new_state = "open" if new_count >= self.threshold else state.get("state", "closed")
        if not bid:
            bid = _gen_id("cb")
            self._conn.execute(
                """INSERT INTO circuit_breakers
                   (breaker_id, component, state, failure_count, last_failure_at, opened_at, threshold)
                   VALUES (?,?,?,?,?,?,?)""",
                (bid, self.component, new_state, new_count, now,
                 now if new_state == "open" else None, self.threshold),
            )
        else:
            self._conn.execute(
                """UPDATE circuit_breakers
                   SET state=?, failure_count=?, last_failure_at=?, opened_at=?
                   WHERE breaker_id=?""",
                (new_state, new_count, now,
                 now if new_state == "open" and state.get("state") != "open" else state.get("opened_at"),
                 bid),
            )
        self._conn.commit()

    def reset(self) -> None:
        if not self._conn:
            return
        self._conn.execute(
            "UPDATE circuit_breakers SET state='closed', failure_count=0, success_count=0 WHERE component=?",
            (self.component,),
        )
        self._conn.commit()


class TaskLease:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def acquire(self, task_id: str, worker_id: str, ttl_seconds: float = 300.0) -> dict[str, Any]:
        now = utc_now()
        try:
            expires_ts = datetime.fromisoformat(now).timestamp() + ttl_seconds
            expires_at = datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat()
        except Exception:
            expires_at = now
        existing = self._conn.execute(
            "SELECT * FROM task_leases WHERE task_id=? AND status='active'", (task_id,)
        ).fetchone()
        if existing:
            try:
                exp_ts = datetime.fromisoformat(existing["expires_at"]).timestamp()
                if time.time() < exp_ts:
                    return {"acquired": False, "reason": "already_leased", "by": existing["worker_id"]}
            except Exception:
                pass
        lease_id = _gen_id("lease")
        self._conn.execute(
            "INSERT INTO task_leases (lease_id, task_id, worker_id, acquired_at, expires_at, status) VALUES (?,?,?,?,?,?)",
            (lease_id, task_id, worker_id, now, expires_at, "active"),
        )
        self._conn.commit()
        return {"acquired": True, "lease_id": lease_id, "expires_at": expires_at}

    def release(self, task_id: str, worker_id: str) -> dict[str, Any]:
        self._conn.execute(
            "UPDATE task_leases SET status='released' WHERE task_id=? AND worker_id=? AND status='active'",
            (task_id, worker_id),
        )
        self._conn.commit()
        return {"released": True, "task_id": task_id}

    def is_leased(self, task_id: str) -> bool:
        row = self._conn.execute(
            "SELECT * FROM task_leases WHERE task_id=? AND status='active'", (task_id,)
        ).fetchone()
        if not row:
            return False
        try:
            exp_ts = datetime.fromisoformat(row["expires_at"]).timestamp()
            return time.time() < exp_ts
        except Exception:
            return True

    def cleanup_expired(self) -> int:
        now_ts = time.time()
        rows = self._conn.execute(
            "SELECT lease_id, expires_at FROM task_leases WHERE status='active'"
        ).fetchall()
        expired = 0
        for r in rows:
            try:
                exp_ts = datetime.fromisoformat(r["expires_at"]).timestamp()
                if now_ts >= exp_ts:
                    self._conn.execute(
                        "UPDATE task_leases SET status='expired' WHERE lease_id=?", (r["lease_id"],)
                    )
                    expired += 1
            except Exception:
                self._conn.execute(
                    "UPDATE task_leases SET status='expired' WHERE lease_id=?", (r["lease_id"],)
                )
                expired += 1
        self._conn.commit()
        return expired


class AdvancedScheduler:
    """Scheduler con prioridades dinámicas, cuotas, leases, backoff,
    circuit breaker, DLQ y balanceo de carga."""

    TASK_TYPES = [
        "pulse_check", "pending_learning_review",
        "semantic_memory_governance", "neuron_candidate_formation",
        "experimental_neuron_activity", "neuron_autopromotion",
        "federation_inbox_review", "memory_consolidation_review",
        "stable_consolidation_review", "system_debt_scan",
        "bodega_global_review", "shell_execute",
    ]

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._ensure_defaults()
        self._leases = TaskLease(self._conn)
        self._breakers: dict[str, CircuitBreaker] = {}

    def _ensure_defaults(self) -> None:
        now = utc_now()
        for tt in self.TASK_TYPES:
            self._conn.execute(
                "INSERT OR IGNORE INTO scheduler_priorities (task_type, base_priority, current_priority, updated_at) VALUES (?,?,?,?)",
                (tt, 10, 10, now),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO scheduler_quotas (task_type, max_per_hour, max_per_day, hour_reset_at, day_reset_at) VALUES (?,?,?,?,?)",
                (tt, 100, 1000, now, now),
            )
        self._conn.commit()

    def get_breaker(self, component: str) -> CircuitBreaker:
        if component not in self._breakers:
            self._breakers[component] = CircuitBreaker(component, conn=self._conn)
        return self._breakers[component]

    def acquire_lease(self, task_id: str, worker_id: str, ttl_seconds: float = 300.0) -> dict[str, Any]:
        return self._leases.acquire(task_id, worker_id, ttl_seconds)

    def release_lease(self, task_id: str, worker_id: str) -> dict[str, Any]:
        return self._leases.release(task_id, worker_id)

    def is_task_leased(self, task_id: str) -> bool:
        return self._leases.is_leased(task_id)

    def cleanup_expired_leases(self) -> int:
        return self._leases.cleanup_expired()

    def retry_with_backoff(self, func, max_retries: int = 3, base_delay: float = 1.0,
                            component: str = "default") -> Any:
        breaker = self.get_breaker(component)
        if not breaker.allows_request:
            raise RuntimeError(f"Circuit breaker OPEN for {component}")
        last_exc = None
        for attempt in range(max_retries):
            try:
                result = func()
                breaker.record_success()
                return result
            except Exception as exc:
                last_exc = exc
                breaker.record_failure()
                delay = base_delay * (2 ** attempt)
                log.warning("Retry %d/%d for %s after %.1fs: %s", attempt + 1, max_retries, component, delay, exc)
                time.sleep(delay)
        raise last_exc or RuntimeError(f"All {max_retries} retries failed for {component}")

    def boost_priority(self, task_type: str, amount: int = 2) -> dict[str, Any]:
        self._conn.execute(
            "UPDATE scheduler_priorities SET current_priority=MIN(current_priority+?, 50), updated_at=? WHERE task_type=?",
            (amount, utc_now(), task_type),
        )
        self._conn.commit()
        return {"task_type": task_type, "new_priority": self._get_priority(task_type)}

    def decay_priorities(self) -> int:
        now = utc_now()
        rows = self._conn.execute("SELECT task_type, current_priority, base_priority, decay_rate FROM scheduler_priorities").fetchall()
        updated = 0
        for r in rows:
            cur = r["current_priority"]
            base = r["base_priority"]
            rate = r["decay_rate"]
            if cur > base:
                new_p = max(base, int(cur - (cur - base) * rate))
                self._conn.execute(
                    "UPDATE scheduler_priorities SET current_priority=?, updated_at=? WHERE task_type=?",
                    (new_p, now, r["task_type"]),
                )
                updated += 1
        self._conn.commit()
        return updated

    def _get_priority(self, task_type: str) -> int:
        row = self._conn.execute(
            "SELECT current_priority FROM scheduler_priorities WHERE task_type=?", (task_type,)
        ).fetchone()
        return row["current_priority"] if row else 10

    def get_all_priorities(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM scheduler_priorities ORDER BY current_priority DESC").fetchall()
        return [dict(r) for r in rows]

    def check_quota(self, task_type: str) -> dict[str, Any]:
        row = self._conn.execute("SELECT * FROM scheduler_quotas WHERE task_type=?", (task_type,)).fetchone()
        if not row:
            return {"allowed": True, "reason": "no quota"}
        q = dict(row)
        now = utc_now()
        self._maybe_reset(q, now)
        hour_ok = q["used_hour"] < q["max_per_hour"]
        day_ok = q["used_day"] < q["max_per_day"]
        return {
            "allowed": hour_ok and day_ok,
            "used_hour": q["used_hour"], "max_per_hour": q["max_per_hour"],
            "used_day": q["used_day"], "max_per_day": q["max_per_day"],
            "reason": "" if (hour_ok and day_ok) else ("hourly" if not hour_ok else "daily"),
        }

    def consume_quota(self, task_type: str) -> dict[str, Any]:
        self._conn.execute(
            "UPDATE scheduler_quotas SET used_hour=used_hour+1, used_day=used_day+1 WHERE task_type=?",
            (task_type,),
        )
        self._conn.commit()
        return self.check_quota(task_type)

    def _maybe_reset(self, q: dict, now: str) -> None:
        if q["used_hour"] > 0 and q["hour_reset_at"] and q["hour_reset_at"][:13] < now[:13]:
            self._conn.execute("UPDATE scheduler_quotas SET used_hour=0, hour_reset_at=? WHERE task_type=?", (now, q["task_type"]))
        if q["used_day"] > 0 and q["day_reset_at"] and q["day_reset_at"][:10] < now[:10]:
            self._conn.execute("UPDATE scheduler_quotas SET used_day=0, day_reset_at=? WHERE task_type=?", (now, q["task_type"]))
        self._conn.commit()

    def heartbeat(self, worker_id: str, status: str = "active",
                  tasks_running: int = 0, cpu_pct: float = 0.0,
                  mem_mb: float = 0.0, metadata: dict | None = None) -> dict[str, Any]:
        now = utc_now()
        meta = json.dumps(metadata or {}, default=str)
        self._conn.execute(
            """INSERT INTO worker_heartbeats
               (worker_id, last_heartbeat, status, tasks_running, cpu_pct, mem_mb, metadata_json)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(worker_id) DO UPDATE SET
                 last_heartbeat=?, status=?, tasks_running=?, cpu_pct=?, mem_mb=?, metadata_json=?""",
            (worker_id, now, status, tasks_running, cpu_pct, mem_mb, meta,
             now, status, tasks_running, cpu_pct, mem_mb, meta),
        )
        self._conn.commit()
        return {"worker_id": worker_id, "heartbeat": now}

    def stale_workers(self, timeout_seconds: int = 120) -> list[dict[str, Any]]:
        now = time.time()
        rows = self._conn.execute("SELECT * FROM worker_heartbeats WHERE status != 'stopped'").fetchall()
        stale: list[dict[str, Any]] = []
        for r in rows:
            try:
                ts = datetime.fromisoformat(r["last_heartbeat"]).timestamp()
            except Exception:
                ts = 0
            if now - ts > timeout_seconds:
                stale.append(dict(r))
        return stale

    def active_workers(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM worker_heartbeats WHERE status='active' ORDER BY last_heartbeat DESC").fetchall()
        return [dict(r) for r in rows]

    def send_to_dlq(self, task_id: str, task_type: str, payload: dict,
                    failure_reason: str, attempts: int) -> dict[str, Any]:
        dlq_id = _gen_id("dlq")
        self._conn.execute(
            """INSERT INTO dead_letter_queue
               (dlq_id, task_id, task_type, payload_json, failure_reason, attempts, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (dlq_id, task_id, task_type, json.dumps(payload, default=str),
             failure_reason, attempts, utc_now()),
        )
        self._conn.commit()
        return {"dlq_id": dlq_id, "task_id": task_id, "reason": failure_reason}

    def resolve_dlq(self, dlq_id: str) -> dict[str, Any]:
        self._conn.execute("UPDATE dead_letter_queue SET resolved=1 WHERE dlq_id=?", (dlq_id,))
        self._conn.commit()
        return {"dlq_id": dlq_id, "resolved": True}

    def list_dlq(self, resolved: bool = False) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM dead_letter_queue WHERE resolved=? ORDER BY created_at DESC",
            (1 if resolved else 0,),
        ).fetchall()
        return [dict(r) for r in rows]

    def snapshot_load(self) -> dict[str, Any]:
        workers = self.active_workers()
        n_workers = len(workers)
        avg_cpu = sum(w.get("cpu_pct", 0) for w in workers) / max(n_workers, 1)
        avg_mem = sum(w.get("mem_mb", 0) for w in workers) / max(n_workers, 1)
        tasks_running = sum(w.get("tasks_running", 0) for w in workers)
        load_score = _clamp((avg_cpu / 100.0) * 0.5 + (tasks_running / max(n_workers * 3, 1)) * 0.3 + (avg_mem / 30000.0) * 0.2)
        snap_id = _gen_id("loadsnap")
        self._conn.execute(
            """INSERT INTO scheduler_load_snapshots
               (snapshot_id, worker_count, tasks_queued, tasks_running, load_score, created_at)
               VALUES (?,?,?,?,?,?)""",
            (snap_id, n_workers, 0, tasks_running, round(load_score, 4), utc_now()),
        )
        self._conn.commit()
        return {"worker_count": n_workers, "tasks_running": tasks_running, "load_score": round(load_score, 4)}

    def should_throttle(self) -> bool:
        return self.snapshot_load()["load_score"] > 0.85

    def recommend_task(self, available_tasks: list[str]) -> str | None:
        scored: list[tuple[str, int]] = []
        for tt in available_tasks:
            if not self.check_quota(tt)["allowed"]:
                continue
            scored.append((tt, self._get_priority(tt)))
        if not scored:
            return None
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]

    def doctor(self) -> dict[str, Any]:
        priorities = self._conn.execute("SELECT COUNT(*) as c FROM scheduler_priorities").fetchone()["c"]
        heartbeats = self._conn.execute("SELECT COUNT(*) as c FROM worker_heartbeats").fetchone()["c"]
        dlq = self._conn.execute("SELECT COUNT(*) as c FROM dead_letter_queue WHERE resolved=0").fetchone()["c"]
        leases = self._conn.execute("SELECT COUNT(*) as c FROM task_leases WHERE status='active'").fetchone()["c"]
        breakers = self._conn.execute("SELECT COUNT(*) as c FROM circuit_breakers WHERE state='open'").fetchone()["c"]
        return {
            "priorities": priorities, "heartbeats": heartbeats,
            "dlq_pending": dlq, "active_leases": leases, "open_breakers": breakers,
        }
