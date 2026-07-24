"""T-010 — Scheduler avanzado: prioridades dinámicas, cuotas por tipo de
tarea, heartbeat de workers, Dead Letter Queue, balanceo de carga."""

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS scheduler_priorities (
    task_type      TEXT PRIMARY KEY,
    base_priority  INTEGER DEFAULT 10,
    current_priority INTEGER DEFAULT 10,
    decay_rate     REAL DEFAULT 0.05,
    boost_on_fail  INTEGER DEFAULT 2,
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
CREATE TABLE IF NOT EXISTS dead_letter_queue (
    dlq_id         TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL,
    task_type      TEXT NOT NULL,
    payload_json   TEXT DEFAULT '{}',
    failure_reason TEXT DEFAULT '',
    attempts       INTEGER DEFAULT 0,
    last_error     TEXT DEFAULT '',
    created_at     TEXT NOT NULL,
    resolved       INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scheduler_load_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    worker_count   INTEGER DEFAULT 0,
    tasks_queued   INTEGER DEFAULT 0,
    tasks_running  INTEGER DEFAULT 0,
    avg_cpu_pct    REAL DEFAULT 0.0,
    avg_mem_mb     REAL DEFAULT 0.0,
    load_score     REAL DEFAULT 0.0,
    created_at     TEXT NOT NULL
);
"""


class AdvancedScheduler:
    """Scheduler con prioridades dinámicas, cuotas, heartbeat, DLQ y
    balanceo de carga."""

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

    def _ensure_defaults(self):
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

    # ─── dynamic priorities ───

    def boost_priority(self, task_type: str, amount: int = 2) -> dict:
        self._conn.execute(
            """UPDATE scheduler_priorities
               SET current_priority = MIN(current_priority + ?, 50), updated_at=?
               WHERE task_type=?""",
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
            "SELECT current_priority FROM scheduler_priorities WHERE task_type=?",
            (task_type,),
        ).fetchone()
        return row["current_priority"] if row else 10

    def get_effective_priority(self, task_type: str, failure_count: int = 0) -> int:
        base = self._get_priority(task_type)
        boost = min(failure_count * 2, 10)
        return min(base + boost, 50)

    def get_all_priorities(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM scheduler_priorities ORDER BY current_priority DESC").fetchall()
        return [dict(r) for r in rows]

    # ─── quotas ───

    def check_quota(self, task_type: str) -> dict:
        row = self._conn.execute(
            "SELECT * FROM scheduler_quotas WHERE task_type=?", (task_type,)
        ).fetchone()
        if not row:
            return {"allowed": True, "reason": "no quota configured"}
        q = dict(row)
        now = utc_now()
        self._maybe_reset(q, now)
        hour_ok = q["used_hour"] < q["max_per_hour"]
        day_ok = q["used_day"] < q["max_per_day"]
        return {
            "allowed": hour_ok and day_ok,
            "used_hour": q["used_hour"],
            "max_per_hour": q["max_per_hour"],
            "used_day": q["used_day"],
            "max_per_day": q["max_per_day"],
            "reason": "" if (hour_ok and day_ok) else ("hourly limit" if not hour_ok else "daily limit"),
        }

    def consume_quota(self, task_type: str) -> dict:
        self._conn.execute(
            "UPDATE scheduler_quotas SET used_hour = used_hour + 1, used_day = used_day + 1 WHERE task_type=?",
            (task_type,),
        )
        self._conn.commit()
        return self.check_quota(task_type)

    def set_quota(self, task_type: str, max_per_hour: int, max_per_day: int):
        self._conn.execute(
            """INSERT INTO scheduler_quotas (task_type, max_per_hour, max_per_day, hour_reset_at, day_reset_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(task_type) DO UPDATE SET max_per_hour=?, max_per_day=?""",
            (task_type, max_per_hour, max_per_day, utc_now(), utc_now(), max_per_hour, max_per_day),
        )
        self._conn.commit()

    def _maybe_reset(self, q: dict, now: str):
        # simplified: reset if hour/day changed
        if q["used_hour"] > 0 and q["hour_reset_at"] and q["hour_reset_at"][:13] < now[:13]:
            self._conn.execute("UPDATE scheduler_quotas SET used_hour=0, hour_reset_at=? WHERE task_type=?", (now, q["task_type"]))
        if q["used_day"] > 0 and q["day_reset_at"] and q["day_reset_at"][:10] < now[:10]:
            self._conn.execute("UPDATE scheduler_quotas SET used_day=0, day_reset_at=? WHERE task_type=?", (now, q["task_type"]))
        self._conn.commit()

    # ─── heartbeat ───

    def heartbeat(self, worker_id: str, status: str = "active",
                  tasks_running: int = 0, cpu_pct: float = 0.0,
                  mem_mb: float = 0.0, metadata: dict | None = None) -> dict:
        now = utc_now()
        self._conn.execute(
            """INSERT INTO worker_heartbeats (worker_id, last_heartbeat, status, tasks_running, cpu_pct, mem_mb, metadata_json)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(worker_id) DO UPDATE SET
                 last_heartbeat=?, status=?, tasks_running=?, cpu_pct=?, mem_mb=?, metadata_json=?""",
            (worker_id, now, status, tasks_running, cpu_pct, mem_mb,
             json.dumps(metadata or {}, default=str),
             now, status, tasks_running, cpu_pct, mem_mb,
             json.dumps(metadata or {}, default=str)),
        )
        self._conn.commit()
        return {"worker_id": worker_id, "heartbeat": now}

    def stale_workers(self, timeout_seconds: int = 120) -> list[dict]:
        now = time.time()
        rows = self._conn.execute("SELECT * FROM worker_heartbeats WHERE status != 'stopped'").fetchall()
        stale = []
        for r in rows:
            try:
                ts = datetime.fromisoformat(r["last_heartbeat"]).timestamp()
            except Exception:
                ts = 0
            if now - ts > timeout_seconds:
                stale.append(dict(r))
        return stale

    def active_workers(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM worker_heartbeats WHERE status='active' ORDER BY last_heartbeat DESC").fetchall()
        return [dict(r) for r in rows]

    # ─── dead letter queue ───

    def send_to_dlq(self, task_id: str, task_type: str, payload: dict,
                    failure_reason: str, attempts: int, last_error: str) -> dict:
        dlq_id = _gen_id("dlq")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO dead_letter_queue
               (dlq_id, task_id, task_type, payload_json, failure_reason,
                attempts, last_error, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (dlq_id, task_id, task_type, json.dumps(payload, default=str),
             failure_reason, attempts, last_error, now),
        )
        self._conn.commit()
        return {"dlq_id": dlq_id, "task_id": task_id, "reason": failure_reason}

    def resolve_dlq(self, dlq_id: str) -> dict:
        self._conn.execute(
            "UPDATE dead_letter_queue SET resolved=1 WHERE dlq_id=?", (dlq_id,)
        )
        self._conn.commit()
        return {"dlq_id": dlq_id, "resolved": True}

    def list_dlq(self, resolved: bool = False) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM dead_letter_queue WHERE resolved=? ORDER BY created_at DESC",
            (1 if resolved else 0,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── load balancing ───

    def snapshot_load(self) -> dict:
        now = utc_now()
        workers = self.active_workers()
        n_workers = len(workers)
        avg_cpu = sum(w.get("cpu_pct", 0) for w in workers) / max(n_workers, 1)
        avg_mem = sum(w.get("mem_mb", 0) for w in workers) / max(n_workers, 1)

        from triade.workers.worker_loop import WorkerLoop
        # approximate queued/running from heartbeats
        tasks_running = sum(w.get("tasks_running", 0) for w in workers)
        load_score = _clamp((avg_cpu / 100.0) * 0.5 + (tasks_running / max(n_workers * 3, 1)) * 0.3 + (avg_mem / 30000.0) * 0.2)

        snap_id = _gen_id("loadsnap")
        self._conn.execute(
            """INSERT INTO scheduler_load_snapshots
               (snapshot_id, worker_count, tasks_queued, tasks_running,
                avg_cpu_pct, avg_mem_mb, load_score, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (snap_id, n_workers, 0, tasks_running, round(avg_cpu, 2),
             round(avg_mem, 2), round(load_score, 4), now),
        )
        self._conn.commit()
        return {
            "worker_count": n_workers,
            "tasks_running": tasks_running,
            "avg_cpu_pct": round(avg_cpu, 2),
            "avg_mem_mb": round(avg_mem, 2),
            "load_score": round(load_score, 4),
        }

    def should_throttle(self) -> bool:
        snap = self.snapshot_load()
        return snap["load_score"] > 0.85

    def recommend_task(self, available_tasks: list[str]) -> str | None:
        if not available_tasks:
            return None
        scored = []
        for tt in available_tasks:
            quota = self.check_quota(tt)
            if not quota["allowed"]:
                continue
            p = self._get_priority(tt)
            scored.append((tt, p))
        if not scored:
            return None
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]

    # ─── diagnostics ───

    def doctor(self) -> dict:
        priorities = self._conn.execute("SELECT COUNT(*) as c FROM scheduler_priorities").fetchone()["c"]
        quotas = self._conn.execute("SELECT COUNT(*) as c FROM scheduler_quotas").fetchone()["c"]
        heartbeats = self._conn.execute("SELECT COUNT(*) as c FROM worker_heartbeats").fetchone()["c"]
        dlq = self._conn.execute("SELECT COUNT(*) as c FROM dead_letter_queue WHERE resolved=0").fetchone()["c"]
        return {
            "priorities": priorities,
            "quotas": quotas,
            "heartbeats": heartbeats,
            "dlq_pending": dlq,
        }
