"""T-011 — Supervisión de Workers: tracking de consumo, tiempo, owner,
restart automático, recovery post-fallo, supervisión en tiempo real."""

import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS worker_consumption (
    record_id      TEXT PRIMARY KEY,
    worker_id      TEXT NOT NULL,
    task_id        TEXT,
    task_type      TEXT DEFAULT '',
    cpu_seconds    REAL DEFAULT 0.0,
    memory_peak_mb REAL DEFAULT 0.0,
    disk_read_mb   REAL DEFAULT 0.0,
    disk_write_mb  REAL DEFAULT 0.0,
    gpu_seconds    REAL DEFAULT 0.0,
    tokens_used    INTEGER DEFAULT 0,
    recorded_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wc_worker ON worker_consumption(worker_id);
CREATE TABLE IF NOT EXISTS worker_time_log (
    log_id         TEXT PRIMARY KEY,
    worker_id      TEXT NOT NULL,
    task_id        TEXT NOT NULL,
    task_type      TEXT DEFAULT '',
    started_at     TEXT NOT NULL,
    finished_at    TEXT,
    duration_ms    REAL DEFAULT 0.0,
    status         TEXT DEFAULT 'running'
);
CREATE INDEX IF NOT EXISTS idx_wt_worker ON worker_time_log(worker_id);
CREATE TABLE IF NOT EXISTS worker_ownership (
    owner_id       TEXT PRIMARY KEY,
    worker_id      TEXT NOT NULL,
    task_id        TEXT NOT NULL,
    claimed_at     TEXT NOT NULL,
    released_at    TEXT,
    reason         TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_wown_worker ON worker_ownership(worker_id);
CREATE TABLE IF NOT EXISTS worker_restart_log (
    restart_id     TEXT PRIMARY KEY,
    worker_id      TEXT NOT NULL,
    trigger        TEXT NOT NULL,
    reason         TEXT DEFAULT '',
    recovery_status TEXT DEFAULT 'pending',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS worker_health_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    worker_id      TEXT NOT NULL,
    status         TEXT DEFAULT 'unknown',
    cpu_pct        REAL DEFAULT 0.0,
    mem_mb         REAL DEFAULT 0.0,
    tasks_running  INTEGER DEFAULT 0,
    uptime_seconds REAL DEFAULT 0.0,
    last_error     TEXT DEFAULT '',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_whs_worker ON worker_health_snapshots(worker_id);
"""


class WorkerSupervisor:
    """Supervisor de workers: tracking de consumo, tiempo, ownership,
    restart automático, recovery, y health snapshots en tiempo real."""

    MAX_TASK_DURATION_MS = 300_000  # 5 minutes
    MAX_MEMORY_MB = 4096
    MAX_CPU_SECONDS = 600
    RESTART_THRESHOLD_FAILURES = 3

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    # ─── consumption tracking ───

    def record_consumption(
        self, worker_id: str, task_id: str | None = None,
        task_type: str = "", cpu_seconds: float = 0.0,
        memory_peak_mb: float = 0.0, disk_read_mb: float = 0.0,
        disk_write_mb: float = 0.0, gpu_seconds: float = 0.0,
        tokens_used: int = 0,
    ) -> dict:
        record_id = _gen_id("cons")
        self._conn.execute(
            """INSERT INTO worker_consumption
               (record_id, worker_id, task_id, task_type,
                cpu_seconds, memory_peak_mb, disk_read_mb, disk_write_mb,
                gpu_seconds, tokens_used, recorded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (record_id, worker_id, task_id, task_type,
             cpu_seconds, memory_peak_mb, disk_read_mb, disk_write_mb,
             gpu_seconds, tokens_used, utc_now()),
        )
        self._conn.commit()
        return {"record_id": record_id, "worker_id": worker_id}

    def worker_consumption(self, worker_id: str, since_hours: int = 24) -> dict:
        rows = self._conn.execute(
            "SELECT * FROM worker_consumption WHERE worker_id=? ORDER BY recorded_at DESC",
            (worker_id,),
        ).fetchall()
        total_cpu = sum(r["cpu_seconds"] for r in rows)
        total_mem = max((r["memory_peak_mb"] for r in rows), default=0.0)
        total_tokens = sum(r["tokens_used"] for r in rows)
        return {
            "worker_id": worker_id,
            "records": len(rows),
            "total_cpu_seconds": round(total_cpu, 2),
            "peak_memory_mb": round(total_mem, 2),
            "total_tokens": total_tokens,
        }

    def over_limit_workers(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT worker_id, SUM(cpu_seconds) as total_cpu, MAX(memory_peak_mb) as peak_mem
               FROM worker_consumption GROUP BY worker_id"""
        ).fetchall()
        over = []
        for r in rows:
            reasons = []
            if r["total_cpu"] > self.MAX_CPU_SECONDS:
                reasons.append("cpu_over_limit")
            if r["peak_mem"] > self.MAX_MEMORY_MB:
                reasons.append("memory_over_limit")
            if reasons:
                over.append({"worker_id": r["worker_id"], "reasons": reasons})
        return over

    # ─── time tracking ───

    def start_task(self, worker_id: str, task_id: str, task_type: str = "") -> dict:
        log_id = _gen_id("timelog")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO worker_time_log
               (log_id, worker_id, task_id, task_type, started_at, status)
               VALUES (?,?,?,?,?,?)""",
            (log_id, worker_id, task_id, task_type, now, "running"),
        )
        self._conn.commit()
        return {"log_id": log_id, "started_at": now}

    def finish_task(self, log_id: str, status: str = "completed") -> dict:
        now = utc_now()
        row = self._conn.execute(
            "SELECT started_at FROM worker_time_log WHERE log_id=?", (log_id,)
        ).fetchone()
        if not row:
            return {"error": "log not found"}
        try:
            start_ts = datetime.fromisoformat(row["started_at"]).timestamp()
            dur = (time.time() - start_ts) * 1000
        except Exception:
            dur = 0.0
        self._conn.execute(
            "UPDATE worker_time_log SET finished_at=?, duration_ms=?, status=? WHERE log_id=?",
            (now, round(dur, 2), status, log_id),
        )
        self._conn.commit()
        return {"log_id": log_id, "duration_ms": round(dur, 2), "status": status}

    def stuck_tasks(self, timeout_ms: float = 300_000) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM worker_time_log WHERE status='running'"
        ).fetchall()
        stuck = []
        now = time.time()
        for r in rows:
            try:
                start_ts = datetime.fromisoformat(r["started_at"]).timestamp()
                dur = (now - start_ts) * 1000
                if dur > timeout_ms:
                    stuck.append({**dict(r), "elapsed_ms": round(dur, 2)})
            except Exception:
                stuck.append(dict(r))
        return stuck

    def time_summary(self, worker_id: str) -> dict:
        rows = self._conn.execute(
            "SELECT * FROM worker_time_log WHERE worker_id=?", (worker_id,)
        ).fetchall()
        completed = [r for r in rows if r["status"] == "completed"]
        failed = [r for r in rows if r["status"] == "failed"]
        avg_dur = sum(r["duration_ms"] for r in completed) / max(len(completed), 1)
        return {
            "worker_id": worker_id,
            "total_tasks": len(rows),
            "completed": len(completed),
            "failed": len(failed),
            "avg_duration_ms": round(avg_dur, 2),
        }

    # ─── owner tracking ───

    def claim_task(self, worker_id: str, task_id: str, reason: str = "") -> dict:
        owner_id = _gen_id("own")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO worker_ownership
               (owner_id, worker_id, task_id, claimed_at, reason)
               VALUES (?,?,?,?,?)""",
            (owner_id, worker_id, task_id, now, reason),
        )
        self._conn.commit()
        return {"owner_id": owner_id, "worker_id": worker_id, "task_id": task_id}

    def release_task(self, owner_id: str, reason: str = "") -> dict:
        self._conn.execute(
            "UPDATE worker_ownership SET released_at=?, reason=? WHERE owner_id=?",
            (utc_now(), reason, owner_id),
        )
        self._conn.commit()
        return {"owner_id": owner_id, "released": True}

    def task_owner(self, task_id: str) -> dict | None:
        row = self._conn.execute(
            """SELECT * FROM worker_ownership
               WHERE task_id=? AND released_at IS NULL
               ORDER BY claimed_at DESC LIMIT 1""",
            (task_id,),
        ).fetchone()
        return dict(row) if row else None

    # ─── auto restart & recovery ───

    def request_restart(self, worker_id: str, trigger: str, reason: str = "") -> dict:
        restart_id = _gen_id("restart")
        self._conn.execute(
            """INSERT INTO worker_restart_log
               (restart_id, worker_id, trigger, reason, recovery_status, created_at)
               VALUES (?,?,?,?,?,?)""",
            (restart_id, worker_id, trigger, reason, "pending", utc_now()),
        )
        self._conn.commit()
        return {"restart_id": restart_id, "worker_id": worker_id, "status": "pending"}

    def complete_restart(self, restart_id: str, status: str = "recovered") -> dict:
        self._conn.execute(
            "UPDATE worker_restart_log SET recovery_status=? WHERE restart_id=?",
            (status, restart_id),
        )
        self._conn.commit()
        return {"restart_id": restart_id, "status": status}

    def recovery_needed(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM worker_restart_log WHERE recovery_status='pending'"
        ).fetchall()
        return [dict(r) for r in rows]

    def auto_restart_check(self, worker_id: str, recent_failures: int) -> dict:
        if recent_failures >= self.RESTART_THRESHOLD_FAILURES:
            restart = self.request_restart(worker_id, "auto_restart",
                                           f"{recent_failures} consecutive failures")
            return {"action": "restart", "restart": restart}
        return {"action": "none", "failures": recent_failures}

    # ─── real-time supervision ───

    def health_snapshot(
        self, worker_id: str, status: str = "healthy",
        cpu_pct: float = 0.0, mem_mb: float = 0.0,
        tasks_running: int = 0, uptime_seconds: float = 0.0,
        last_error: str = "",
    ) -> dict:
        snap_id = _gen_id("whsnap")
        self._conn.execute(
            """INSERT INTO worker_health_snapshots
               (snapshot_id, worker_id, status, cpu_pct, mem_mb,
                tasks_running, uptime_seconds, last_error, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (snap_id, worker_id, status, cpu_pct, mem_mb,
             tasks_running, uptime_seconds, last_error, utc_now()),
        )
        self._conn.commit()
        return {"snapshot_id": snap_id, "worker_id": worker_id, "status": status}

    def get_health(self, worker_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM worker_health_snapshots WHERE worker_id=? ORDER BY created_at DESC LIMIT 1",
            (worker_id,),
        ).fetchone()
        return dict(row) if row else None

    def unhealthy_workers(self) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM worker_health_snapshots
               WHERE status IN ('error', 'degraded', 'unhealthy')
               AND created_at > datetime('now', '-1 hour')
               ORDER BY created_at DESC"""
        ).fetchall()
        seen = set()
        result = []
        for r in rows:
            wid = r["worker_id"]
            if wid not in seen:
                seen.add(wid)
                result.append(dict(r))
        return result

    def supervision_summary(self) -> dict:
        total = self._conn.execute(
            "SELECT COUNT(DISTINCT worker_id) as c FROM worker_health_snapshots"
        ).fetchone()["c"]
        healthy = self._conn.execute(
            """SELECT COUNT(DISTINCT worker_id) as c FROM worker_health_snapshots
               WHERE status='healthy' AND created_at > datetime('now', '-1 hour')"""
        ).fetchone()["c"]
        pending_restarts = self._conn.execute(
            "SELECT COUNT(*) as c FROM worker_restart_log WHERE recovery_status='pending'"
        ).fetchone()["c"]
        dlq_tasks = self._conn.execute(
            "SELECT COUNT(*) as c FROM worker_time_log WHERE status='running' AND duration_ms > 300000"
        ).fetchone()["c"]
        return {
            "total_workers": total,
            "healthy": healthy,
            "pending_restarts": pending_restarts,
            "stuck_tasks": dlq_tasks,
        }

    # ─── diagnostics ───

    def doctor(self) -> dict:
        consumption = self._conn.execute("SELECT COUNT(*) as c FROM worker_consumption").fetchone()["c"]
        time_logs = self._conn.execute("SELECT COUNT(*) as c FROM worker_time_log").fetchone()["c"]
        ownership = self._conn.execute(
            "SELECT COUNT(*) as c FROM worker_ownership WHERE released_at IS NULL"
        ).fetchone()["c"]
        restarts = self._conn.execute(
            "SELECT COUNT(*) as c FROM worker_restart_log WHERE recovery_status='pending'"
        ).fetchone()["c"]
        return {
            "consumption_records": consumption,
            "time_logs": time_logs,
            "active_ownership": ownership,
            "pending_restarts": restarts,
        }
