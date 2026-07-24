"""Federated Memory — almacena y sincroniza conocimiento entre nodos
federados con tracking de origen, merge y resolución de conflictos."""

import json
import sqlite3
from typing import Any

from triade.core.contracts import utc_now


def _gen_id(prefix: str) -> str:
    import hashlib
    from datetime import datetime, timezone
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.md5(str(datetime.now(timezone.utc).timestamp()).encode()).hexdigest()[:6]}"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS federated_memory_items (
    item_id        TEXT PRIMARY KEY,
    source_node    TEXT NOT NULL,
    key            TEXT NOT NULL,
    value          TEXT NOT NULL,
    domain         TEXT DEFAULT 'general',
    confidence     REAL DEFAULT 0.8,
    origin_node    TEXT NOT NULL,
    replicated_at  TEXT,
    status         TEXT DEFAULT 'active',
    metadata_json  TEXT DEFAULT '{}',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS fmi_key ON federated_memory_items(key);
CREATE INDEX IF NOT EXISTS fmi_domain ON federated_memory_items(domain);
CREATE TABLE IF NOT EXISTS federated_merge_log (
    merge_id       TEXT PRIMARY KEY,
    source_item_id TEXT NOT NULL,
    target_item_id TEXT,
    action         TEXT NOT NULL,
    conflict_json  TEXT DEFAULT '{}',
    merged_at      TEXT NOT NULL
);
"""


class FederatedMemory:
    """Almacén de memoria compartido entre nodos federados con merge,
    resolución de conflictos y tracking de origen."""

    def __init__(self, db_path: str | None = None, conn: sqlite3.Connection | None = None):
        self._conn = conn or sqlite3.connect(db_path or ":memory:")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def store(self, key: str, value: str, source_node: str,
              domain: str = "general", confidence: float = 0.8,
              origin_node: str = "", metadata: dict | None = None) -> dict:
        item_id = _gen_id("fmem")
        now = utc_now()
        existing = self._conn.execute(
            "SELECT * FROM federated_memory_items WHERE key=? AND status='active'",
            (key,),
        ).fetchone()

        if existing:
            merge_id = _gen_id("fmerge")
            action = "updated"
            if confidence > existing["confidence"]:
                self._conn.execute(
                    """UPDATE federated_memory_items
                       SET value=?, confidence=?, source_node=?, replicated_at=?, metadata_json=?
                       WHERE item_id=?""",
                    (value, confidence, source_node, now,
                     json.dumps(metadata or {}, default=str), existing["item_id"]),
                )
            else:
                action = "kept_existing"
            self._conn.execute(
                """INSERT INTO federated_merge_log
                   (merge_id, source_item_id, target_item_id, action, merged_at)
                   VALUES (?,?,?,?,?)""",
                (merge_id, item_id, existing["item_id"], action, now),
            )
            self._conn.commit()
            return {"item_id": existing["item_id"], "action": action, "merge_id": merge_id}
        else:
            self._conn.execute(
                """INSERT INTO federated_memory_items
                   (item_id, source_node, key, value, domain, confidence,
                    origin_node, replicated_at, metadata_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (item_id, source_node, key, value, domain, confidence,
                 origin_node or source_node, now,
                 json.dumps(metadata or {}, default=str), now),
            )
            self._conn.commit()
            return {"item_id": item_id, "action": "created"}

    def retrieve(self, key: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM federated_memory_items WHERE key=? AND status='active'",
            (key,),
        ).fetchone()
        return dict(row) if row else None

    def search(self, domain: str = "", source_node: str = "",
               limit: int = 50) -> list[dict]:
        query = "SELECT * FROM federated_memory_items WHERE status='active'"
        params: list = []
        if domain:
            query += " AND domain=?"
            params.append(domain)
        if source_node:
            query += " AND source_node=?"
            params.append(source_node)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def deprecate(self, key: str) -> dict:
        self._conn.execute(
            "UPDATE federated_memory_items SET status='deprecated' WHERE key=?",
            (key,),
        )
        self._conn.commit()
        return {"key": key, "status": "deprecated"}

    def merge_log(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM federated_merge_log ORDER BY merged_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def doctor(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) as c FROM federated_memory_items WHERE status='active'").fetchone()["c"]
        nodes = self._conn.execute("SELECT COUNT(DISTINCT source_node) as c FROM federated_memory_items").fetchone()["c"]
        merges = self._conn.execute("SELECT COUNT(*) as c FROM federated_merge_log").fetchone()["c"]
        return {"active_items": total, "source_nodes": nodes, "merge_operations": merges}
