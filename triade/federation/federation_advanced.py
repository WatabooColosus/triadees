"""T-018 — Federación avanzada: trust scoring expandido, worker federation,
resource sharing, y replication entre nodos."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS federation_trust_scores (
    node_id        TEXT PRIMARY KEY,
    trust_score    REAL DEFAULT 0.5,
    reliability    REAL DEFAULT 0.5,
    latency_ms     REAL DEFAULT 0.0,
    success_rate   REAL DEFAULT 1.0,
    uptime_pct     REAL DEFAULT 100.0,
    total_tasks    INTEGER DEFAULT 0,
    failed_tasks   INTEGER DEFAULT 0,
    last_seen      TEXT,
    updated_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS federation_workers (
    federation_id  TEXT PRIMARY KEY,
    local_worker_id TEXT NOT NULL,
    remote_node_id TEXT NOT NULL,
    task_type      TEXT NOT NULL,
    status         TEXT DEFAULT 'idle',
    assigned_task  TEXT DEFAULT '',
    capability_json TEXT DEFAULT '[]',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS federation_resources (
    share_id       TEXT PRIMARY KEY,
    node_id        TEXT NOT NULL,
    resource_type  TEXT NOT NULL,
    total_units    REAL DEFAULT 0.0,
    shared_units   REAL DEFAULT 0.0,
    used_units     REAL DEFAULT 0.0,
    status         TEXT DEFAULT 'available',
    created_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS federation_replication (
    replica_id     TEXT PRIMARY KEY,
    source_node    TEXT NOT NULL,
    target_node    TEXT NOT NULL,
    data_type      TEXT NOT NULL,
    data_id        TEXT NOT NULL,
    status         TEXT DEFAULT 'pending',
    replicated_at  TEXT,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fr_data ON federation_replication(data_type, data_id);
"""


class FederationAdvanced:
    """Federación avanzada con trust scoring, worker federation,
    resource sharing y replication."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    # ─── trust scoring ───

    def update_trust(
        self, node_id: str, success: bool = True,
        latency_ms: float = 0.0,
    ) -> dict:
        now = utc_now()
        row = self._conn.execute(
            "SELECT * FROM federation_trust_scores WHERE node_id=?", (node_id,)
        ).fetchone()
        if row:
            r = dict(row)
            total = r["total_tasks"] + 1
            failed = r["failed_tasks"] + (0 if success else 1)
            success_rate = 1.0 - failed / max(total, 1)
            avg_lat = (r["latency_ms"] * r["total_tasks"] + latency_ms) / max(total, 1)
            trust = _clamp(0.4 * success_rate + 0.3 * (1.0 - min(avg_lat / 1000, 1.0)) + 0.3 * r["uptime_pct"] / 100)
            self._conn.execute(
                """UPDATE federation_trust_scores
                   SET trust_score=?, reliability=?, latency_ms=?,
                       success_rate=?, total_tasks=?, failed_tasks=?,
                       last_seen=?, updated_at=?
                   WHERE node_id=?""",
                (round(trust, 4), round(success_rate, 4), round(avg_lat, 2),
                 round(success_rate, 4), total, failed, now, now, node_id),
            )
        else:
            trust = 0.5 if success else 0.3
            self._conn.execute(
                """INSERT INTO federation_trust_scores
                   (node_id, trust_score, reliability, latency_ms,
                    success_rate, total_tasks, failed_tasks,
                    last_seen, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (node_id, trust, trust, latency_ms, 1.0 if success else 0.0,
                 1, 0 if success else 1, now, now),
            )
        self._conn.commit()
        return {"node_id": node_id, "trust_score": round(trust, 4)}

    def get_trust(self, node_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM federation_trust_scores WHERE node_id=?", (node_id,)
        ).fetchone()
        return dict(row) if row else None

    def top_nodes(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM federation_trust_scores ORDER BY trust_score DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def low_trust_nodes(self, threshold: float = 0.3) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM federation_trust_scores WHERE trust_score < ?",
            (threshold,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── worker federation ───

    def register_fed_worker(
        self, local_worker_id: str, remote_node_id: str,
        task_type: str, capabilities: list[str] | None = None,
    ) -> dict:
        fed_id = _gen_id("fwd")
        now = utc_now()
        self._conn.execute(
            """INSERT INTO federation_workers
               (federation_id, local_worker_id, remote_node_id,
                task_type, capability_json, created_at)
               VALUES (?,?,?,?,?,?)""",
            (fed_id, local_worker_id, remote_node_id, task_type,
             json.dumps(capabilities or [], default=str), now),
        )
        self._conn.commit()
        return {"federation_id": fed_id, "remote_node": remote_node_id}

    def assign_fed_task(self, federation_id: str, task_id: str) -> dict:
        self._conn.execute(
            "UPDATE federation_workers SET status='busy', assigned_task=? WHERE federation_id=?",
            (task_id, federation_id),
        )
        self._conn.commit()
        return {"federation_id": federation_id, "task_id": task_id}

    def release_fed_worker(self, federation_id: str) -> dict:
        self._conn.execute(
            "UPDATE federation_workers SET status='idle', assigned_task='' WHERE federation_id=?",
            (federation_id,),
        )
        self._conn.commit()
        return {"federation_id": federation_id, "status": "idle"}

    def idle_fed_workers(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM federation_workers WHERE status='idle'"
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── resource sharing ───

    def share_resource(
        self, node_id: str, resource_type: str,
        total_units: float, shared_units: float,
    ) -> dict:
        share_id = _gen_id("fshare")
        self._conn.execute(
            """INSERT INTO federation_resources
               (share_id, node_id, resource_type, total_units,
                shared_units, created_at)
               VALUES (?,?,?,?,?,?)""",
            (share_id, node_id, resource_type, total_units, shared_units, utc_now()),
        )
        self._conn.commit()
        return {"share_id": share_id, "node_id": node_id, "type": resource_type}

    def available_resources(self, resource_type: str | None = None) -> list[dict]:
        if resource_type:
            rows = self._conn.execute(
                "SELECT * FROM federation_resources WHERE resource_type=? AND status='available'",
                (resource_type,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM federation_resources WHERE status='available'"
            ).fetchall()
        return [dict(r) for r in rows]

    def consume_shared(self, share_id: str, units: float) -> dict:
        row = self._conn.execute(
            "SELECT * FROM federation_resources WHERE share_id=?", (share_id,)
        ).fetchone()
        if not row:
            return {"error": "share not found"}
        r = dict(row)
        new_used = r["used_units"] + units
        if new_used > r["shared_units"]:
            return {"error": "insufficient shared units"}
        self._conn.execute(
            "UPDATE federation_resources SET used_units=? WHERE share_id=?",
            (new_used, share_id),
        )
        self._conn.commit()
        return {"share_id": share_id, "used": new_used, "remaining": r["shared_units"] - new_used}

    # ─── replication ───

    def replicate(
        self, source_node: str, target_node: str,
        data_type: str, data_id: str,
    ) -> dict:
        replica_id = _gen_id("frepl")
        self._conn.execute(
            """INSERT INTO federation_replication
               (replica_id, source_node, target_node, data_type,
                data_id, status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (replica_id, source_node, target_node, data_type,
             data_id, "pending", utc_now()),
        )
        self._conn.commit()
        return {"replica_id": replica_id, "source": source_node, "target": target_node}

    def complete_replica(self, replica_id: str) -> dict:
        self._conn.execute(
            "UPDATE federation_replication SET status='completed', replicated_at=? WHERE replica_id=?",
            (utc_now(), replica_id),
        )
        self._conn.commit()
        return {"replica_id": replica_id, "status": "completed"}

    def pending_replicas(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM federation_replication WHERE status='pending'"
        ).fetchall()
        return [dict(r) for r in rows]

    def doctor(self) -> dict:
        nodes = self._conn.execute("SELECT COUNT(*) as c FROM federation_trust_scores").fetchone()["c"]
        workers = self._conn.execute("SELECT COUNT(*) as c FROM federation_workers").fetchone()["c"]
        resources = self._conn.execute("SELECT COUNT(*) as c FROM federation_resources WHERE status='available'").fetchone()["c"]
        replicas = self._conn.execute("SELECT COUNT(*) as c FROM federation_replication WHERE status='pending'").fetchone()["c"]
        return {"trusted_nodes": nodes, "federated_workers": workers,
                "shared_resources": resources, "pending_replicas": replicas}
