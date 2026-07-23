"""Multi-user isolation system for Tríade Ω.

Each user gets a session with scoped memory, preferences, and history.
Tenant-aware queries filter all memory by user_id.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_session_id() -> str:
    return f"sess-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


@dataclass(slots=True)
class UserSession:
    user_id: str
    session_id: str
    status: str = "active"
    permissions: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    last_active_at: str = ""
    closed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status,
            "permissions": dict(self.permissions),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "closed_at": self.closed_at,
        }


class UserSessionStore:
    """SQLite-backed multi-user session manager."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "memory" / "schemas.sql"
        if schema_path.exists():
            with self._connect() as conn:
                conn.executescript(schema_path.read_text(encoding="utf-8"))

    def create_user(self, user_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT user_id FROM user_sessions WHERE user_id = ? LIMIT 1",
                (user_id,),
            ).fetchone()
            if existing:
                return {"user_id": user_id, "status": "exists"}
            conn.execute(
                """INSERT INTO user_sessions (user_id, session_id, status, permissions, metadata, created_at, last_active_at)
                VALUES (?, ?, 'active', '{}', ?, ?, ?)""",
                (user_id, _new_session_id(), json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
        return {"user_id": user_id, "status": "created"}

    def create_session(self, user_id: str) -> UserSession:
        now = _utc_now()
        session_id = _new_session_id()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO user_sessions (user_id, session_id, status, permissions, metadata, created_at, last_active_at)
                VALUES (?, ?, 'active', '{}', '{}', ?, ?)""",
                (user_id, session_id, now, now),
            )
        return UserSession(
            user_id=user_id,
            session_id=session_id,
            created_at=now,
            last_active_at=now,
        )

    def get_session(self, session_id: str) -> UserSession | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def list_sessions(self, user_id: str, limit: int = 50) -> list[UserSession]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM user_sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [self._row_to_session(r) for r in rows]

    def touch_session(self, session_id: str) -> bool:
        now = _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE user_sessions SET last_active_at = ? WHERE session_id = ? AND status = 'active'",
                (now, session_id),
            )
            return cursor.rowcount > 0

    def close_session(self, session_id: str) -> bool:
        now = _utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE user_sessions SET status = 'closed', closed_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            return cursor.rowcount > 0

    def get_user_context(self, session_id: str) -> dict[str, Any]:
        session = self.get_session(session_id)
        if session is None:
            return {"status": "session_not_found"}
        with self._connect() as conn:
            run_count = conn.execute(
                "SELECT COUNT(*) as c FROM runs WHERE user_id = ?",
                (session.user_id,),
            ).fetchone()
            recent_runs = conn.execute(
                "SELECT run_id, user_input, status, created_at FROM runs WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
                (session.user_id,),
            ).fetchall()
            episodic_count = conn.execute(
                "SELECT COUNT(*) as c FROM episodic_memory em JOIN runs r ON em.run_id = r.run_id WHERE r.user_id = ?",
                (session.user_id,),
            ).fetchone()
        return {
            "status": "ok",
            "session": session.to_dict(),
            "run_count": run_count["c"] if run_count else 0,
            "recent_runs": [dict(r) for r in recent_runs] if recent_runs else [],
            "episodic_count": episodic_count["c"] if episodic_count else 0,
        }

    def get_active_users(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT user_id, COUNT(*) as session_count, MAX(last_active_at) as last_active
                FROM user_sessions WHERE status = 'active' GROUP BY user_id ORDER BY last_active DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _row_to_session(row: sqlite3.Row) -> UserSession:
        def r(key: str, default: object = "") -> object:
            try:
                return row[key]
            except (KeyError, IndexError):
                return default

        try:
            permissions = json.loads(str(r("permissions", "{}")))
        except (json.JSONDecodeError, TypeError):
            permissions = {}
        try:
            metadata = json.loads(str(r("metadata", "{}")))
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        return UserSession(
            user_id=str(r("user_id")),
            session_id=str(r("session_id")),
            status=str(r("status", "active")),
            permissions=permissions,
            metadata=metadata,
            created_at=str(r("created_at", "")),
            last_active_at=str(r("last_active_at", "")),
            closed_at=str(r("closed_at") or None),
        )
