"""Bus interno ligero sobre SQLite existente.

Registra eventos operativos en `worker_events` para mantener trazabilidad sin
crear una base nueva. Si la semántica del evento requiere otro registro, el
supervisor puede persistirlo además en su tabla de dominio.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.core.error_bus import prune_worker_events


def _connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    schema_path = Path(__file__).resolve().parents[1] / "memory" / "schemas.sql"
    if schema_path.exists():
        conn.executescript(schema_path.read_text(encoding="utf-8"))
    return conn


def publish_event(
    event_type: str,
    source: str,
    payload: dict[str, Any] | None,
    severity: str = "info",
    *,
    db_path: str | Path = "triade/memory/triade.db",
    run_ref: str | None = None,
    task_id: int | None = None,
    task_type: str | None = None,
) -> dict[str, Any]:
    """Publica un evento operativo en worker_events."""

    event_payload = {
        "event_type": event_type,
        "source": source,
        "severity": severity,
        "payload": payload or {},
    }
    message = str((payload or {}).get("message") or source or event_type)
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO worker_events
            (run_ref, task_id, task_type, event_type, status, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_ref,
                task_id,
                task_type or source,
                event_type,
                severity,
                message[:240],
                json.dumps(event_payload, ensure_ascii=False)[:4000],
                utc_now(),
            ),
        )
        prune_worker_events(conn)
    return {
        "status": "ok",
        "event_id": int(cursor.lastrowid),
        "event_type": event_type,
        "source": source,
        "severity": severity,
        "created_at": utc_now(),
    }


def list_recent_events(limit: int = 100, db_path: str | Path = "triade/memory/triade.db") -> list[dict[str, Any]]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT id, run_ref, task_id, task_type, event_type, status, message, payload_json, created_at
            FROM worker_events
            ORDER BY id DESC
            LIMIT ?""",
            (limit,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def mark_event_processed(event_id: int, db_path: str | Path = "triade/memory/triade.db") -> dict[str, Any]:
    with _connect(db_path) as conn:
        cursor = conn.execute(
            "UPDATE worker_events SET status = ? WHERE id = ?",
            ("processed", event_id),
        )
    return {
        "status": "ok" if cursor.rowcount else "missing",
        "event_id": event_id,
        "processed": bool(cursor.rowcount),
    }


def build_context_from_events(limit: int = 50, db_path: str | Path = "triade/memory/triade.db") -> dict[str, Any]:
    events = list_recent_events(limit=limit, db_path=db_path)
    by_type: dict[str, int] = {}
    by_source: dict[str, int] = {}
    recent_messages = []
    for event in events:
        event_type = str(event.get("event_type") or "unknown")
        source = str(event.get("task_type") or event.get("source") or "unknown")
        by_type[event_type] = by_type.get(event_type, 0) + 1
        by_source[source] = by_source.get(source, 0) + 1
        recent_messages.append(
            {
                "id": event.get("id"),
                "event_type": event_type,
                "source": source,
                "status": event.get("status"),
                "message": event.get("message"),
                "created_at": event.get("created_at"),
            }
        )
    return {
        "status": "ok",
        "count": len(events),
        "events_by_type": by_type,
        "events_by_source": by_source,
        "recent_events": recent_messages[:limit],
        "policy": {
            "readonly_default": True,
            "processed_marking_is_explicit": True,
            "worker_events_backed": True,
        },
    }


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    payload_raw = item.get("payload_json")
    if payload_raw:
        try:
            item["payload"] = json.loads(payload_raw)
        except (json.JSONDecodeError, TypeError):
            item["payload"] = {"raw": str(payload_raw)[:500]}
    item.pop("payload_json", None)
    return item
