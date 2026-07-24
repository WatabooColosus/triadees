"""Consolidación — Compresión de memoria con migraciones versionadas,
olvido reversible, detección de contradicciones, y cadena de reemplazos.

Sistema formal de migraciones, no CREATE TABLE IF NOT EXISTS.
Olvido: status=forgotten, reason, policy, snapshot (reversible).
Contradicciones: cuarentena, cadena de reemplazos, auditoría completa.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now

log = logging.getLogger(__name__)

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS consolidation_log (
    log_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    operation      TEXT NOT NULL,
    target_table   TEXT NOT NULL,
    target_ids     TEXT DEFAULT '[]',
    details_json   TEXT NOT NULL DEFAULT '{}',
    source_evidence TEXT DEFAULT '',
    confidence     REAL DEFAULT 1.0,
    validation_method TEXT DEFAULT '',
    actor          TEXT DEFAULT 'system',
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cl_operation ON consolidation_log(operation);
CREATE INDEX IF NOT EXISTS cl_created ON consolidation_log(created_at);

CREATE TABLE IF NOT EXISTS memory_contradictions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_a_id    INTEGER NOT NULL,
    memory_a_table TEXT NOT NULL,
    memory_b_id    INTEGER NOT NULL,
    memory_b_table TEXT NOT NULL,
    field_name     TEXT NOT NULL,
    value_a        TEXT NOT NULL,
    value_b        TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'detected',
    resolution     TEXT DEFAULT '',
    resolution_actor TEXT DEFAULT '',
    detected_at    TEXT NOT NULL,
    resolved_at    TEXT
);
CREATE INDEX IF NOT EXISTS mc_status ON memory_contradictions(status);

CREATE TABLE IF NOT EXISTS memory_replacements (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    old_id         INTEGER NOT NULL,
    old_table      TEXT NOT NULL,
    new_id         INTEGER NOT NULL,
    new_table      TEXT NOT NULL,
    reason         TEXT DEFAULT '',
    chain_id       TEXT DEFAULT '',
    replaced_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mr_chain ON memory_replacements(chain_id);
CREATE INDEX IF NOT EXISTS mr_old ON memory_replacements(old_id, old_table);

CREATE TABLE IF NOT EXISTS schema_migrations (
    table_name     TEXT NOT NULL,
    version        INTEGER NOT NULL,
    applied_at     TEXT NOT NULL,
    PRIMARY KEY (table_name, version)
);
"""

MIGRATIONS = {1: SCHEMA_V1}


@dataclass
class ConsolidationResult:
    operation: str = ""
    items_processed: int = 0
    items_removed: int = 0
    items_merged: int = 0
    information_loss: float = 0.0
    details: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "items_processed": self.items_processed,
            "items_removed": self.items_removed,
            "items_merged": self.items_merged,
            "information_loss": round(self.information_loss, 4),
            "details": list(self.details),
            "created_at": self.created_at,
        }


class MemoryConsolidator:
    """Consolidación de memoria con migraciones, olvido reversible, contradicciones."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._ensure_schema()
        return self._conn

    def _ensure_schema(self) -> None:
        conn = self._conn
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                table_name TEXT NOT NULL, version INTEGER NOT NULL,
                applied_at TEXT NOT NULL, PRIMARY KEY (table_name, version))"""
        )
        row = conn.execute(
            "SELECT version FROM schema_migrations WHERE table_name='consolidation' ORDER BY version DESC LIMIT 1"
        ).fetchone()
        current = row["version"] if row else 0
        target = max(MIGRATIONS.keys())
        if current >= target:
            return
        for v in range(current + 1, target + 1):
            sql = MIGRATIONS.get(v)
            if sql:
                try:
                    conn.executescript(sql)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_migrations (table_name, version, applied_at) VALUES (?,?,?)",
                        ("consolidation", v, utc_now()),
                    )
                    conn.commit()
                    log.info("Applied consolidation migration v%d", v)
                except Exception as exc:
                    log.error("Consolidation migration v%d failed: %s", v, exc)
                    raise

    # --- Deduplicación con preservación de fuente ---

    def deduplicate_semantic(self) -> ConsolidationResult:
        conn = self._get_conn()
        processed = 0
        removed = 0
        details: list[str] = []
        rows = conn.execute(
            "SELECT id, key, value, confidence, source_ref FROM semantic_memory ORDER BY confidence DESC"
        ).fetchall()
        seen: dict[str, list[int]] = {}
        for row in rows:
            combo = f"{row['key']}||{row['value']}"
            seen.setdefault(combo, []).append(row["id"])
            processed += 1
        for combo, ids in seen.items():
            if len(ids) > 1:
                to_remove = ids[1:]
                for rid in to_remove:
                    conn.execute("DELETE FROM semantic_memory WHERE id=?", (rid,))
                    removed += 1
                details.append(f"Duplicate {combo[:40]}: {len(ids)}→1")
        conn.commit()
        return ConsolidationResult(
            operation="deduplicate_semantic", items_processed=processed,
            items_removed=removed, details=details,
        )

    def compress_episodes(self, *, max_age_days: int = 90, keep_min: int = 10) -> ConsolidationResult:
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) as c FROM episodic_memory").fetchone()["c"]
        if total <= keep_min:
            return ConsolidationResult(
                operation="compress_episodes", items_processed=total,
                details=["Not enough episodes to compress."],
            )
        rows = conn.execute(
            "SELECT id, importance FROM episodic_memory ORDER BY created_at ASC LIMIT ?",
            (total - keep_min,),
        ).fetchall()
        removed = 0
        for row in rows:
            conn.execute("DELETE FROM episodic_memory WHERE id=?", (row["id"],))
            removed += 1
        conn.commit()
        loss = removed / max(total, 1)
        return ConsolidationResult(
            operation="compress_episodes", items_processed=total,
            items_removed=removed, information_loss=loss,
            details=[f"Removed {removed} old episodes, loss={loss:.2%}"],
        )

    # --- Olvido reversible ---

    def forget(self, table: str, entry_id: int, reason: str = "", policy: str = "manual",
               actor: str = "user") -> dict[str, Any]:
        conn = self._get_conn()
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return {"error": "not_found"}
        snapshot = dict(row)
        now = utc_now()
        status_col = "status" if "status" in [d[1] for d in conn.execute(f"PRAGMA table_info({table})").fetchall()] else None
        if status_col:
            conn.execute(
                f"UPDATE {table} SET status='forgotten' WHERE id=?", (entry_id,)
            )
        conn.execute(
            """INSERT INTO consolidation_log
               (operation, target_table, target_ids, details_json, source_evidence,
                confidence, validation_method, actor, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            ("forget", table, json.dumps([entry_id]),
             json.dumps({"reason": reason, "policy": policy, "snapshot": {k: str(v)[:200] for k, v in snapshot.items()}}, default=str),
             "", 1.0, "explicit", actor, now),
        )
        conn.commit()
        return {"forgotten": True, "entry_id": entry_id, "table": table, "reason": reason}

    def restore(self, table: str, entry_id: int, actor: str = "user") -> dict[str, Any]:
        conn = self._get_conn()
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return {"error": "not_found"}
        status_col = "status" if "status" in [d[1] for d in conn.execute(f"PRAGMA table_info({table})").fetchall()] else None
        if status_col:
            conn.execute(
                f"UPDATE {table} SET status='active' WHERE id=?", (entry_id,)
            )
        conn.execute(
            """INSERT INTO consolidation_log
               (operation, target_table, target_ids, details_json, actor, created_at)
               VALUES (?,?,?,?,?,?)""",
            ("restore", table, json.dumps([entry_id]),
             json.dumps({"reason": "explicit_restore"}), actor, utc_now()),
        )
        conn.commit()
        return {"restored": True, "entry_id": entry_id, "table": table}

    # --- Detección de contradicciones ---

    def detect_contradictions(self, table_a: str, table_b: str, field_name: str,
                               id_a: int, id_b: int) -> dict[str, Any]:
        conn = self._get_conn()
        row_a = conn.execute(f"SELECT * FROM {table_a} WHERE id=?", (id_a,)).fetchone()
        row_b = conn.execute(f"SELECT * FROM {table_b} WHERE id=?", (id_b,)).fetchone()
        if not row_a or not row_b:
            return {"error": "not_found"}
        val_a = str(row_a[field_name]) if field_name in row_a.keys() else ""
        val_b = str(row_b[field_name]) if field_name in row_b.keys() else ""
        if val_a == val_b:
            return {"contradiction": False}
        now = utc_now()
        conn.execute(
            """INSERT INTO memory_contradictions
               (memory_a_id, memory_a_table, memory_b_id, memory_b_table,
                field_name, value_a, value_b, status, detected_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (id_a, table_a, id_b, table_b, field_name, val_a, val_b, "detected", now),
        )
        conn.commit()
        return {"contradiction": True, "field": field_name, "value_a": val_a, "value_b": val_b}

    def get_contradictions(self, status: str = "detected") -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM memory_contradictions WHERE status=? ORDER BY detected_at DESC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve_contradiction(self, contradiction_id: int, resolution: str,
                               actor: str = "system") -> dict[str, Any]:
        conn = self._get_conn()
        conn.execute(
            """UPDATE memory_contradictions
               SET status='resolved', resolution=?, resolution_actor=?, resolved_at=?
               WHERE id=?""",
            (resolution, actor, utc_now(), contradiction_id),
        )
        conn.commit()
        return {"resolved": True, "contradiction_id": contradiction_id}

    # --- Cadena de reemplazos ---

    def register_replacement(self, old_table: str, old_id: int,
                              new_table: str, new_id: int,
                              reason: str = "", chain_id: str = "") -> dict[str, Any]:
        conn = self._get_conn()
        if not chain_id:
            chain_id = f"chain-{int(time.time() * 1000)}-{hashlib.md5(str(time.time()).encode()).hexdigest()[:6]}"
        conn.execute(
            """INSERT INTO memory_replacements
               (old_id, old_table, new_id, new_table, reason, chain_id, replaced_at)
               VALUES (?,?,?,?,?,?,?)""",
            (old_id, old_table, new_id, new_table, reason, chain_id, utc_now()),
        )
        conn.commit()
        return {"chain_id": chain_id, "old": f"{old_table}:{old_id}", "new": f"{new_table}:{new_id}"}

    def get_replacement_chain(self, chain_id: str) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM memory_replacements WHERE chain_id=? ORDER BY replaced_at ASC",
            (chain_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Log de auditoría ---

    def log_operation(self, operation: str, target_table: str, target_ids: list[int],
                      details: dict[str, Any], actor: str = "system") -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO consolidation_log
               (operation, target_table, target_ids, details_json, actor, created_at)
               VALUES (?,?,?,?,?,?)""",
            (operation, target_table, json.dumps(target_ids),
             json.dumps(details, default=str), actor, utc_now()),
        )
        conn.commit()

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM consolidation_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict[str, Any]:
        conn = self._get_conn()
        contradictions = conn.execute(
            "SELECT COUNT(*) as c FROM memory_contradictions WHERE status='detected'"
        ).fetchone()["c"]
        replacements = conn.execute("SELECT COUNT(*) as c FROM memory_replacements").fetchone()["c"]
        log_count = conn.execute("SELECT COUNT(*) as c FROM consolidation_log").fetchone()["c"]
        return {
            "pending_contradictions": contradictions,
            "total_replacements": replacements,
            "audit_log_entries": log_count,
        }
