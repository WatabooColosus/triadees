"""Persistent planning graph for Tríade Ω.

Goal tree with dependencies, decomposition, and lifecycle management.
Replaces fixed-step mission planning with a dynamic goal graph.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _new_goal_id() -> str:
    return f"goal-{uuid.uuid4().hex[:12]}"


GOAL_STATES = frozenset(
    {
        "pending",
        "awaiting_approval",
        "queued",
        "running",
        "replanning",
        "completed",
        "blocked",
        "failed",
        "expired",
        "cancelled",
        "archived",
    }
)
GOAL_TERMINAL_STATES = frozenset(
    {"completed", "blocked", "failed", "expired", "cancelled", "archived"}
)
GOAL_ACTIVE_STATES = GOAL_STATES - GOAL_TERMINAL_STATES
GOAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset(
        {"awaiting_approval", "queued", "blocked", "expired", "cancelled"}
    ),
    "awaiting_approval": frozenset({"queued", "blocked", "expired", "cancelled"}),
    "queued": frozenset(
        {
            "running",
            "replanning",
            "completed",
            "blocked",
            "failed",
            "expired",
            "cancelled",
        }
    ),
    "running": frozenset(
        {"replanning", "completed", "blocked", "failed", "expired", "cancelled"}
    ),
    "replanning": frozenset({"queued", "blocked", "failed", "expired", "cancelled"}),
    "completed": frozenset({"archived"}),
    "blocked": frozenset({"archived"}),
    "failed": frozenset({"archived"}),
    "expired": frozenset({"archived"}),
    "cancelled": frozenset({"archived"}),
    "archived": frozenset(),
}


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
                (
                    goal_id,
                    parent_id,
                    title,
                    description,
                    priority,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            if dependencies:
                for dep_id in dependencies:
                    conn.execute(
                        "INSERT OR IGNORE INTO goal_dependencies (goal_id, depends_on_id, created_at) VALUES (?, ?, ?)",
                        (goal_id, dep_id, now),
                    )
            self._insert_event(
                conn,
                goal_id,
                event_type="created",
                from_status=None,
                to_status="pending",
                actor=str((metadata or {}).get("source") or "planning_graph"),
                reason="goal_created",
                evidence={"parent_id": parent_id, "dependencies": dependencies or []},
                created_at=now,
            )
        return GoalNode(
            goal_id=goal_id,
            parent_id=parent_id,
            title=title,
            description=description,
            priority=priority,
            dependencies=dependencies or [],
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

    def get_goal(self, goal_id: str) -> GoalNode | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM planning_graph WHERE goal_id = ?", (goal_id,)
            ).fetchone()
            if row is None:
                return None
            deps = conn.execute(
                "SELECT depends_on_id FROM goal_dependencies WHERE goal_id = ?",
                (goal_id,),
            ).fetchall()
        node = self._row_to_goal(row)
        node.dependencies = [str(d["depends_on_id"]) for d in deps]
        return node

    def transition(
        self,
        goal_id: str,
        status: str,
        *,
        actor: str,
        reason: str,
        event_type: str = "status_changed",
        evidence: dict[str, Any] | None = None,
    ) -> GoalNode:
        if status not in GOAL_STATES:
            raise ValueError(f"unknown_goal_status:{status}")
        current = self.get_goal(goal_id)
        if current is None:
            raise ValueError(f"goal_not_found:{goal_id}")
        if current.status == status:
            return current
        if current.status in GOAL_TERMINAL_STATES and status != "archived":
            raise ValueError(f"goal_terminal:{current.status}")
        allowed = GOAL_TRANSITIONS.get(current.status, frozenset())
        if status not in allowed:
            raise ValueError(f"invalid_goal_transition:{current.status}->{status}")
        now = _utc_now()
        completed_at = now if status in GOAL_TERMINAL_STATES else None
        with self._connect() as conn:
            conn.execute(
                "UPDATE planning_graph SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at) WHERE goal_id = ?",
                (status, now, completed_at, goal_id),
            )
            self._insert_event(
                conn,
                goal_id,
                event_type=event_type,
                from_status=current.status,
                to_status=status,
                actor=actor,
                reason=reason,
                evidence=evidence or {},
                created_at=now,
            )
        updated = self.get_goal(goal_id)
        if updated is None:  # pragma: no cover - guarded by the transaction
            raise RuntimeError(f"goal_disappeared:{goal_id}")
        return updated

    def update_status(self, goal_id: str, status: str) -> GoalNode | None:
        """Compatibilidad gobernada para consumidores históricos."""
        return self.transition(
            goal_id,
            status,
            actor="planning_graph.compat",
            reason="legacy_update_status",
        )

    def record_event(
        self,
        goal_id: str,
        *,
        event_type: str,
        actor: str,
        reason: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        goal = self.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"goal_not_found:{goal_id}")
        with self._connect() as conn:
            self._insert_event(
                conn,
                goal_id,
                event_type=event_type,
                from_status=goal.status,
                to_status=goal.status,
                actor=actor,
                reason=reason,
                evidence=evidence or {},
                created_at=_utc_now(),
            )

    def get_events(self, goal_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM goal_events WHERE goal_id=? ORDER BY created_at,event_id",
                (goal_id,),
            ).fetchall()
        return [self._decode_event(row) for row in rows]

    def find_active_by_request_key(self, request_key: str) -> GoalNode | None:
        placeholders = ",".join("?" for _ in GOAL_ACTIVE_STATES)
        with self._connect() as conn:
            row = conn.execute(
                f"""SELECT * FROM planning_graph
                WHERE parent_id IS NULL
                  AND json_extract(metadata, '$.request_key')=?
                  AND status IN ({placeholders})
                ORDER BY created_at LIMIT 1""",
                (request_key, *sorted(GOAL_ACTIVE_STATES)),
            ).fetchone()
        return self._row_to_goal(row) if row is not None else None

    def reconcile_limbo(
        self, *, max_age_minutes: int, actor: str = "goal_reconciler"
    ) -> dict[str, Any]:
        cutoff = (datetime.now(UTC) - timedelta(minutes=max_age_minutes)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT goal_id FROM planning_graph
                WHERE parent_id IS NULL AND status IN ('pending','awaiting_approval','queued','running','replanning')
                  AND updated_at < ? ORDER BY created_at""",
                (cutoff,),
            ).fetchall()
        expired = []
        for row in rows:
            goal_id = str(row["goal_id"])
            for child in self.get_children(goal_id):
                if child.status in GOAL_ACTIVE_STATES:
                    self.transition(
                        child.goal_id,
                        "expired",
                        actor=actor,
                        reason="historical_limbo_policy",
                        event_type="historical_limbo_expired",
                    )
            self.transition(
                goal_id,
                "expired",
                actor=actor,
                reason="historical_limbo_policy",
                event_type="historical_limbo_expired",
            )
            expired.append(goal_id)
        return {"examined": len(rows), "expired": len(expired), "goal_ids": expired}

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        goal_id: str,
        *,
        event_type: str,
        from_status: str | None,
        to_status: str,
        actor: str,
        reason: str,
        evidence: dict[str, Any],
        created_at: str,
    ) -> None:
        conn.execute(
            """INSERT INTO goal_events
            (event_id,goal_id,event_type,from_status,to_status,actor,reason,evidence_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                f"goal-event-{uuid.uuid4().hex[:16]}",
                goal_id,
                event_type,
                from_status,
                to_status,
                actor,
                reason,
                json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                created_at,
            ),
        )

    @staticmethod
    def _decode_event(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["evidence"] = json.loads(str(item.pop("evidence_json") or "{}"))
        except (json.JSONDecodeError, TypeError):
            item["evidence"] = {}
        return item

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
                    "SELECT depends_on_id FROM goal_dependencies WHERE goal_id = ?",
                    (node.goal_id,),
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

    def decompose(
        self, goal_id: str, sub_goals: list[dict[str, Any]]
    ) -> list[GoalNode]:
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
        _utc_now()
        with self._connect() as conn:
            try:
                conn.execute(
                    "UPDATE planning_graph SET metadata = json_set(COALESCE(metadata, '{}'), '$.run_id', ?) WHERE goal_id = ?",
                    (run_id, goal_id),
                )
                return True
            except (
                OSError,
                ImportError,
                sqlite3.Error,
                RuntimeError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
            ):
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
            priority=int(str(r("priority", 3))),
            metadata=meta,
            created_at=str(r("created_at", "")),
            updated_at=str(r("updated_at", "")),
            completed_at=str(r("completed_at")) if r("completed_at") else None,
        )
