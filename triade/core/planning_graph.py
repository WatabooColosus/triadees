"""Persistent planning graph for Tríade Ω.

Goal tree with dependencies, decomposition, and lifecycle management.
Replaces fixed-step mission planning with a dynamic goal graph.
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


def _new_goal_id() -> str:
    return f"goal-{uuid.uuid4().hex[:12]}"


@dataclass(slots=True)
class GoalNode:
    goal_id: str
    parent_id: str | None = None
    title: str = ""
    description: str = ""
    status: str = "pending"
    priority: int = 3
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "parent_id": self.parent_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "dependencies": list(self.dependencies),
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }


class PlanningGraph:
    """Persistent goal tree with dependency tracking in SQLite."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "memory" / "schemas.sql"
        if schema_path.exists():
            with self._connect() as conn:
                conn.executescript(schema_path.read_text(encoding="utf-8"))

    def create_goal(
        self,
        title: str,
        description: str = "",
        parent_id: str | None = None,
        priority: int = 3,
        dependencies: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GoalNode:
        now = _utc_now()
        goal_id = _new_goal_id()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO planning_graph (goal_id, parent_id, title, description, status, priority, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
                (goal_id, parent_id, title, description, priority, json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
            if dependencies:
                for dep_id in dependencies:
                    conn.execute(
                        "INSERT OR IGNORE INTO goal_dependencies (goal_id, depends_on_id, created_at) VALUES (?, ?, ?)",
                        (goal_id, dep_id, now),
                    )
        return GoalNode(
            goal_id=goal_id, parent_id=parent_id, title=title, description=description,
            priority=priority, dependencies=dependencies or [], metadata=metadata or {},
            created_at=now, updated_at=now,
        )

    def get_goal(self, goal_id: str) -> GoalNode | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM planning_graph WHERE goal_id = ?", (goal_id,)).fetchone()
            if row is None:
                return None
            deps = conn.execute(
                "SELECT depends_on_id FROM goal_dependencies WHERE goal_id = ?", (goal_id,)
            ).fetchall()
        node = self._row_to_goal(row)
        node.dependencies = [str(d["depends_on_id"]) for d in deps]
        return node

    def update_status(self, goal_id: str, status: str) -> GoalNode | None:
        now = _utc_now()
        completed_at = now if status == "completed" else None
        with self._connect() as conn:
            conn.execute(
                "UPDATE planning_graph SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at) WHERE goal_id = ?",
                (status, now, completed_at, goal_id),
            )
        return self.get_goal(goal_id)

    def add_dependency(self, goal_id: str, depends_on_id: str) -> bool:
        now = _utc_now()
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO goal_dependencies (goal_id, depends_on_id, created_at) VALUES (?, ?, ?)",
                    (goal_id, depends_on_id, now),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def get_children(self, parent_id: str) -> list[GoalNode]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM planning_graph WHERE parent_id = ? ORDER BY priority ASC, created_at ASC",
                (parent_id,),
            ).fetchall()
        goals = []
        for row in rows:
            node = self._row_to_goal(row)
            deps = conn.execute(
                "SELECT depends_on_id FROM goal_dependencies WHERE goal_id = ?", (node.goal_id,)
            ).fetchall()
            node.dependencies = [str(d["depends_on_id"]) for d in deps]
            goals.append(node)
        return goals

    def get_root_goals(self) -> list[GoalNode]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM planning_graph WHERE parent_id IS NULL AND status != 'archived' ORDER BY priority ASC, created_at ASC"
            ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def get_ready_goals(self) -> list[GoalNode]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT pg.* FROM planning_graph pg
                WHERE pg.status = 'pending'
                AND NOT EXISTS (
                    SELECT 1 FROM goal_dependencies gd
                    JOIN planning_graph dep ON gd.depends_on_id = dep.goal_id
                    WHERE gd.goal_id = pg.goal_id AND dep.status != 'completed'
                )
                ORDER BY pg.priority ASC"""
            ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def get_blocked_goals(self) -> list[GoalNode]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT pg.* FROM planning_graph pg
                JOIN goal_dependencies gd ON pg.goal_id = gd.goal_id
                JOIN planning_graph dep ON gd.depends_on_id = dep.goal_id
                WHERE pg.status = 'pending' AND dep.status != 'completed'
                ORDER BY pg.priority ASC"""
            ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def get_plan_summary(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts = conn.execute(
                "SELECT status, COUNT(*) as c FROM planning_graph GROUP BY status"
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) as c FROM planning_graph").fetchone()
            ready = len(self.get_ready_goals())
            blocked = len(self.get_blocked_goals())
        return {
            "total": total["c"] if total else 0,
            "by_status": {r["status"]: r["c"] for r in counts},
            "ready_now": ready,
            "blocked": blocked,
        }

    def decompose(self, goal_id: str, sub_goals: list[dict[str, Any]]) -> list[GoalNode]:
        results = []
        for sg in sub_goals:
            node = self.create_goal(
                title=sg.get("title", ""),
                description=sg.get("description", ""),
                parent_id=goal_id,
                priority=sg.get("priority", 3),
                dependencies=sg.get("dependencies"),
                metadata=sg.get("metadata"),
            )
            results.append(node)
        return results

    def archive_completed(self, max_age_days: int = 30) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE planning_graph SET status = 'archived'
                WHERE status = 'completed' AND completed_at < datetime('now', ?)""",
                (f"-{max_age_days} days",),
            )
            return cursor.rowcount

    def connect_to_run(self, run_id: str, goal_id: str) -> bool:
        """Vincula un goal a un run_id para trazabilidad."""
        now = _utc_now()
        with self._connect() as conn:
            try:
                conn.execute(
                    "UPDATE planning_graph SET metadata = json_set(COALESCE(metadata, '{}'), '$.run_id', ?) WHERE goal_id = ?",
                    (run_id, goal_id),
                )
                return True
            except Exception:
                return False

    def get_goals_for_run(self, run_id: str) -> list[GoalNode]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM planning_graph WHERE json_extract(metadata, '$.run_id') = ? ORDER BY priority ASC",
                (run_id,),
            ).fetchall()
        return [self._row_to_goal(r) for r in rows]

    def steps_summary(self) -> dict[str, Any]:
        """Resumen del grafo para uso por Central."""
        summary = self.get_plan_summary()
        ready = self.get_ready_goals()
        blocked = self.get_blocked_goals()
        summary["ready_titles"] = [g.title for g in ready[:10]]
        summary["blocked_titles"] = [g.title for g in blocked[:10]]
        return summary

    @staticmethod
    def _row_to_goal(row: sqlite3.Row) -> GoalNode:
        def r(key: str, default: object = "") -> object:
            try:
                return row[key]
            except (KeyError, IndexError):
                return default
        try:
            meta = json.loads(str(r("metadata", "{}")))
        except (json.JSONDecodeError, TypeError):
            meta = {}
        return GoalNode(
            goal_id=str(r("goal_id")),
            parent_id=str(r("parent_id")) if r("parent_id") else None,
            title=str(r("title", "")),
            description=str(r("description", "")),
            status=str(r("status", "pending")),
            priority=int(r("priority", 3)),
            metadata=meta,
            created_at=str(r("created_at", "")),
            updated_at=str(r("updated_at", "")),
            completed_at=str(r("completed_at")) if r("completed_at") else None,
        )
