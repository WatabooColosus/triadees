"""Grafo durable de objetivos, dependencias, leases y replanificación."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


class DurableGoalGraph:
    TERMINAL = {"completed", "failed", "cancelled"}

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS durable_goals (
                    goal_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
                    title TEXT NOT NULL, acceptance_json TEXT NOT NULL, status TEXT NOT NULL,
                    priority INTEGER NOT NULL, plan_version INTEGER NOT NULL DEFAULT 1,
                    attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
                    lease_owner TEXT, lease_expires_at REAL, last_error TEXT,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS durable_goal_dependencies (
                    goal_id TEXT NOT NULL, depends_on TEXT NOT NULL,
                    PRIMARY KEY(goal_id, depends_on),
                    FOREIGN KEY(goal_id) REFERENCES durable_goals(goal_id),
                    FOREIGN KEY(depends_on) REFERENCES durable_goals(goal_id)
                );
                CREATE TABLE IF NOT EXISTS durable_goal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id TEXT NOT NULL,
                    event TEXT NOT NULL, payload_json TEXT NOT NULL, created_at REAL NOT NULL
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def create(self, *, title: str, tenant_id: str, user_id: str,
               acceptance: list[str], dependencies: list[str] | None = None,
               priority: int = 50, max_attempts: int = 3, goal_id: str | None = None) -> dict[str, Any]:
        if not title.strip() or not acceptance:
            raise ValueError("title y criterios de aceptación son obligatorios")
        goal_id = goal_id or f"goal-{uuid4().hex[:16]}"
        dependencies = dependencies or []
        now = time.time()
        with self._connect() as conn:
            for dep in dependencies:
                if not conn.execute("SELECT 1 FROM durable_goals WHERE goal_id=?", (dep,)).fetchone():
                    raise KeyError(f"dependencia inexistente: {dep}")
            conn.execute(
                """INSERT INTO durable_goals
                (goal_id,tenant_id,user_id,title,acceptance_json,status,priority,max_attempts,created_at,updated_at)
                VALUES (?,?,?,?,?,'pending',?,?,?,?)""",
                (goal_id, tenant_id, user_id, title, json.dumps(acceptance, ensure_ascii=False),
                 int(priority), int(max_attempts), now, now),
            )
            conn.executemany("INSERT INTO durable_goal_dependencies(goal_id,depends_on) VALUES (?,?)",
                             [(goal_id, dep) for dep in dependencies])
            self._event(conn, goal_id, "created", {"dependencies": dependencies}, now)
        return self.get(goal_id) or {}

    def ready(self, tenant_id: str, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        now = time.time()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT g.* FROM durable_goals g
                WHERE g.tenant_id=? AND g.user_id=? AND g.status IN ('pending','replanned')
                AND (g.lease_expires_at IS NULL OR g.lease_expires_at < ?)
                AND NOT EXISTS (
                  SELECT 1 FROM durable_goal_dependencies d JOIN durable_goals p ON p.goal_id=d.depends_on
                  WHERE d.goal_id=g.goal_id AND p.status!='completed'
                ) ORDER BY g.priority DESC,g.created_at LIMIT ?""",
                (tenant_id, user_id, now, limit),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def acquire(self, goal_id: str, owner: str, ttl_seconds: float = 300) -> bool:
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status,lease_expires_at FROM durable_goals WHERE goal_id=?", (goal_id,)).fetchone()
            if not row or row["status"] in self.TERMINAL or (row["lease_expires_at"] and row["lease_expires_at"] >= now):
                return False
            conn.execute(
                "UPDATE durable_goals SET status='in_progress',lease_owner=?,lease_expires_at=?,attempts=attempts+1,updated_at=? WHERE goal_id=?",
                (owner, now + ttl_seconds, now, goal_id),
            )
            self._event(conn, goal_id, "acquired", {"owner": owner}, now)
        return True

    def complete(self, goal_id: str, owner: str, evidence_refs: list[str]) -> dict[str, Any]:
        if not evidence_refs:
            raise ValueError("completion requiere evidencia")
        return self._transition_owned(goal_id, owner, "completed", {"evidence_refs": evidence_refs})

    def fail_and_replan(self, goal_id: str, owner: str, error: str, revised_acceptance: list[str] | None = None) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM durable_goals WHERE goal_id=? AND lease_owner=?", (goal_id, owner)).fetchone()
            if not row:
                raise PermissionError("lease no pertenece al owner")
            terminal = int(row["attempts"]) >= int(row["max_attempts"])
            status = "failed" if terminal else "replanned"
            acceptance = json.dumps(revised_acceptance, ensure_ascii=False) if revised_acceptance else row["acceptance_json"]
            conn.execute(
                """UPDATE durable_goals SET status=?,acceptance_json=?,plan_version=plan_version+1,
                lease_owner=NULL,lease_expires_at=NULL,last_error=?,updated_at=? WHERE goal_id=?""",
                (status, acceptance, error[:1000], now, goal_id),
            )
            self._event(conn, goal_id, status, {"error": error, "revised": bool(revised_acceptance)}, now)
        return self.get(goal_id) or {}

    def get(self, goal_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM durable_goals WHERE goal_id=?", (goal_id,)).fetchone()
            if not row:
                return None
            deps = [r[0] for r in conn.execute("SELECT depends_on FROM durable_goal_dependencies WHERE goal_id=?", (goal_id,))]
            events = [dict(r) for r in conn.execute("SELECT event,payload_json,created_at FROM durable_goal_events WHERE goal_id=? ORDER BY id", (goal_id,))]
        payload = self._decode(row)
        payload["dependencies"] = deps
        payload["events"] = [{**e, "payload": json.loads(e.pop("payload_json"))} for e in events]
        return payload

    def _transition_owned(self, goal_id: str, owner: str, status: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM durable_goals WHERE goal_id=? AND lease_owner=?", (goal_id, owner)).fetchone()
            if not row:
                raise PermissionError("lease no pertenece al owner")
            conn.execute("UPDATE durable_goals SET status=?,lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE goal_id=?",
                         (status, now, goal_id))
            self._event(conn, goal_id, status, payload, now)
        return self.get(goal_id) or {}

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["acceptance"] = json.loads(value.pop("acceptance_json"))
        return value

    @staticmethod
    def _event(conn: sqlite3.Connection, goal_id: str, event: str, payload: dict[str, Any], now: float) -> None:
        conn.execute("INSERT INTO durable_goal_events(goal_id,event,payload_json,created_at) VALUES (?,?,?,?)",
                     (goal_id, event, json.dumps(payload, sort_keys=True), now))
