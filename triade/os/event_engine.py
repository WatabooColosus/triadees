"""Motor de eventos activo para TriadeOS.

Escanea eventos recientes del event bus, los compara contra reglas declarativas,
y genera WorkerTasks automáticamente. Incluye cooldown y deduplicación.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now
from triade.os.contracts import EventRule, SEVERITY_ORDER


# ── Reglas built-in ──────────────────────────────────────────

BUILTIN_RULES: list[EventRule] = [
    EventRule(
        event_type_pattern=r"^error.*",
        severity_min="warning",
        action="neuron_candidate_formation",
        priority=30,
        cooldown_seconds=300,
        dedup_window_seconds=120,
    ),
    EventRule(
        event_type_pattern=r"^learning_candidate_created$",
        action="pending_learning_review",
        priority=20,
        cooldown_seconds=60,
        dedup_window_seconds=60,
    ),
    EventRule(
        event_type_pattern=r"^neuron_mission_completed$",
        action="neuron_autopromotion",
        priority=25,
        cooldown_seconds=120,
        dedup_window_seconds=120,
    ),
    EventRule(
        event_type_pattern=r"^semantic_document_added$",
        action="pending_learning_review",
        priority=22,
        cooldown_seconds=120,
        dedup_window_seconds=60,
    ),
    EventRule(
        event_type_pattern=r"^federation_exchange_received$",
        action="federation_inbox_review",
        priority=35,
        cooldown_seconds=300,
        dedup_window_seconds=120,
    ),
    EventRule(
        event_type_pattern=r"^pulse_check_completed$",
        action="bodega_global_review",
        priority=40,
        cooldown_seconds=600,
        dedup_window_seconds=300,
    ),
]


class EventEngine:
    """Motor de eventos que genera trabajo automático desde cambios del sistema."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._rules: list[EventRule] = list(BUILTIN_RULES)
        self._ensure_state_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_state_table(self) -> None:
        migration = Path(__file__).resolve().parents[1] / "memory" / "migrations" / "005_triade_os.sql"
        if migration.exists():
            with self._connect() as conn:
                conn.executescript(migration.read_text(encoding="utf-8"))

    # ── Rule management ──────────────────────────────────────

    def register_rule(self, rule: EventRule) -> None:
        self._rules.append(rule)

    def get_rules(self) -> list[EventRule]:
        return list(self._rules)

    def clear_custom_rules(self) -> None:
        self._rules = list(BUILTIN_RULES)

    # ── Core: scan ───────────────────────────────────────────

    def scan(self, batch_size: int = 50) -> list[dict[str, Any]]:
        last_id = self._get_state("last_processed_event_id")
        last_id_int = int(last_id) if last_id else 0

        with self._connect() as conn:
            events = conn.execute(
                """SELECT id, event_type, status AS severity, message, payload_json, created_at
                FROM worker_events
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?""",
                (last_id_int, batch_size),
            ).fetchall()

        created_tasks: list[dict[str, Any]] = []
        max_id = last_id_int

        for event in events:
            eid = int(event["id"])
            if eid > max_id:
                max_id = eid

            event_type = event["event_type"] or ""
            severity = event["severity"] or "ok"
            payload = self._decode_payload(event["payload_json"])

            for rule in self._rules:
                if self._matches_rule(event_type, severity, rule):
                    if self._is_in_cooldown(rule, event_type):
                        continue
                    if self._is_duplicate_pending(rule.action):
                        continue

                    task = self._create_task(
                        rule.action,
                        rule.priority,
                        {
                            "trigger_event_id": eid,
                            "trigger_event_type": event_type,
                            "triggered_by": "event_engine",
                        },
                    )
                    if task:
                        created_tasks.append(task)
                        self._record_trigger(rule, event_type, eid)

        if max_id > last_id_int:
            self._set_state("last_processed_event_id", str(max_id))

        return created_tasks

    def process_single_event(
        self,
        event_id: int,
        rules: list[EventRule] | None = None,
    ) -> list[dict[str, Any]]:
        active_rules = rules or self._rules

        with self._connect() as conn:
            event = conn.execute(
                "SELECT id, event_type, status AS severity, payload_json FROM worker_events WHERE id = ?",
                (event_id,),
            ).fetchone()

        if not event:
            return []

        event_type = event["event_type"] or ""
        severity = event["severity"] or "ok"
        created: list[dict[str, Any]] = []

        for rule in active_rules:
            if self._matches_rule(event_type, severity, rule):
                if self._is_in_cooldown(rule, event_type):
                    continue
                if self._is_duplicate_pending(rule.action):
                    continue
                task = self._create_task(
                    rule.action,
                    rule.priority,
                    {"trigger_event_id": event_id, "trigger_event_type": event_type, "triggered_by": "event_engine"},
                )
                if task:
                    created.append(task)
                    self._record_trigger(rule, event_type, event_id)

        return created

    # ── Matching ─────────────────────────────────────────────

    @staticmethod
    def _matches_rule(event_type: str, severity: str, rule: EventRule) -> bool:
        if not re.search(rule.event_type_pattern, event_type):
            return False
        if rule.source_pattern and not re.search(rule.source_pattern, event_type):
            return False
        event_sev = SEVERITY_ORDER.get(severity, 0)
        rule_sev = SEVERITY_ORDER.get(rule.severity_min, 0)
        return event_sev >= rule_sev

    def _is_in_cooldown(self, rule: EventRule, event_type: str) -> bool:
        if rule.cooldown_seconds <= 0:
            return False
        key = f"cooldown:{rule.action}:{event_type}"
        last_str = self._get_state(key)
        if not last_str:
            return False
        try:
            from datetime import datetime
            last = datetime.fromisoformat(last_str)
            now = datetime.fromisoformat(utc_now())
            return (now - last).total_seconds() < rule.cooldown_seconds
        except (ValueError, TypeError):
            return False

    def _is_duplicate_pending(self, action: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM worker_tasks WHERE task_type = ? AND status = 'pending'",
                (action,),
            ).fetchone()
        return int(row["c"]) > 0

    # ── Task creation ────────────────────────────────────────

    def _create_task(self, task_type: str, priority: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        from triade.os.contracts import SEVERITY_ORDER  # avoid circular at module level already imported

        now = utc_now()
        payload_json = __import__("json").dumps(payload, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO worker_tasks (task_type, status, priority, payload_json, created_at)
                VALUES (?, 'pending', ?, ?, ?)""",
                (task_type, priority, payload_json, now),
            )
            task_id = int(cursor.lastrowid)
        return {"task_id": task_id, "task_type": task_type, "priority": priority, "created_at": now}

    def _record_trigger(self, rule: EventRule, event_type: str, event_id: int) -> None:
        now = utc_now()
        self._set_state(f"cooldown:{rule.action}:{event_type}", now)
        self._set_state(f"last_trigger:{rule.action}", f"{event_id}:{now}")

    # ── State persistence ────────────────────────────────────

    def _get_state(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM triadeos_event_state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def _set_state(self, key: str, value: str) -> None:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO triadeos_event_state (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (key, value, now),
            )

    # ── Doctor ───────────────────────────────────────────────

    def doctor(self) -> dict[str, Any]:
        last_id = self._get_state("last_processed_event_id")
        with self._connect() as conn:
            total_events = conn.execute("SELECT COUNT(*) AS c FROM worker_events").fetchone()["c"]
            pending_tasks = conn.execute(
                "SELECT COUNT(*) AS c FROM worker_tasks WHERE status = 'pending'"
            ).fetchone()["c"]
        return {
            "status": "ok",
            "rules_count": len(self._rules),
            "last_processed_event_id": int(last_id) if last_id else 0,
            "total_events": total_events,
            "pending_tasks_generated": pending_tasks,
            "builtin_rules": [r.event_type_pattern for r in BUILTIN_RULES],
        }

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _decode_payload(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            import json
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
