from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.metabolism.contracts import MetabolicNeed, ResourceBudget

logger = logging.getLogger(__name__)


NEED_DEFAULTS: dict[str, dict[str, Any]] = {
    "health_check": {
        "priority": 90,
        "risk": "none",
        "min_frequency_seconds": 30.0,
        "cooldown_seconds": 10.0,
        "authorization_policy": "always",
    },
    "heartbeat": {
        "priority": 80,
        "risk": "none",
        "min_frequency_seconds": 5.0,
        "cooldown_seconds": 2.0,
        "authorization_policy": "always",
    },
    "lease_supervision": {
        "priority": 70,
        "risk": "low",
        "min_frequency_seconds": 60.0,
        "cooldown_seconds": 15.0,
        "authorization_policy": "always",
    },
    "budget_check": {
        "priority": 60,
        "risk": "none",
        "min_frequency_seconds": 120.0,
        "cooldown_seconds": 30.0,
        "authorization_policy": "always",
    },
    "memory_maintenance": {
        "priority": 50,
        "risk": "low",
        "min_frequency_seconds": 300.0,
        "cooldown_seconds": 60.0,
        "authorization_policy": "on_threshold",
    },
    "contradiction_detection": {
        "priority": 40,
        "risk": "low",
        "min_frequency_seconds": 600.0,
        "cooldown_seconds": 120.0,
        "authorization_policy": "on_threshold",
    },
    "backlog_review": {
        "priority": 30,
        "risk": "medium",
        "min_frequency_seconds": 900.0,
        "cooldown_seconds": 300.0,
        "authorization_policy": "on_threshold",
    },
    "artifact_review": {
        "priority": 30,
        "risk": "low",
        "min_frequency_seconds": 3600.0,
        "cooldown_seconds": 600.0,
        "authorization_policy": "on_threshold",
    },
    "snapshot_maintenance": {
        "priority": 20,
        "risk": "low",
        "min_frequency_seconds": 86400.0,
        "cooldown_seconds": 3600.0,
        "authorization_policy": "on_threshold",
    },
    "internal_task_generation": {
        "priority": 10,
        "risk": "medium",
        "min_frequency_seconds": 0.0,
        "cooldown_seconds": 60.0,
        "authorization_policy": "on_threshold",
    },
}


class NeedsQueue:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._cooldowns: dict[str, float] = {}

    def detect(self, sensors: dict[str, Any], cycle_id: int) -> list[MetabolicNeed]:
        needs: list[MetabolicNeed] = []

        if sensors.get("healthy", True):
            needs.append(self._create_need("health_check", {"sensors_ok": True}))
        else:
            needs.append(
                self._create_need(
                    "health_check",
                    {"sensors_ok": False, "issues": sensors.get("db", {}).get("error")},
                    priority=95,
                )
            )

        heartbeat = sensors.get("heartbeat", {})
        if not heartbeat.get("ok", False):
            needs.append(
                self._create_need(
                    "heartbeat",
                    {"heartbeat_stale": True, "detail": heartbeat.get("error", "")},
                    priority=95,
                )
            )
        else:
            needs.append(self._create_need("heartbeat", {"heartbeat_ok": True}))

        leases = sensors.get("leases", {})
        if not leases.get("ok", True):
            stale = leases.get("stale_leases", 0)
            needs.append(
                self._create_need(
                    "lease_supervision",
                    {"stale_leases": stale},
                    priority=min(70 + stale * 5, 95),
                )
            )

        needs.append(
            self._create_need("budget_check", {"cycle_id": cycle_id})
        )

        return needs

    def _create_need(
        self, kind: str, evidence: dict[str, Any], priority: int | None = None
    ) -> MetabolicNeed:
        defaults = NEED_DEFAULTS.get(kind, {})
        budget = ResourceBudget(
            cpu_seconds_max=5.0,
            ram_mb_max=128.0,
            duration_seconds_max=15.0,
        )
        return MetabolicNeed(
            need_id=f"{kind}-{uuid.uuid4().hex[:12]}",
            kind=kind,
            priority=priority if priority is not None else defaults.get("priority", 50),
            evidence=evidence,
            estimated_cost=budget,
            risk=str(defaults.get("risk", "low")),
            min_frequency_seconds=float(defaults.get("min_frequency_seconds", 30.0)),
            cooldown_seconds=float(defaults.get("cooldown_seconds", 10.0)),
            authorization_policy=str(defaults.get("authorization_policy", "always")),
        )

    def is_on_cooldown(self, need: MetabolicNeed) -> bool:
        import time

        now = time.monotonic()
        last = self._cooldowns.get(need.kind, 0.0)
        if now - last < need.cooldown_seconds:
            return True
        self._cooldowns[need.kind] = now
        return False

    def persist_need(self, need: MetabolicNeed, cycle_id: int) -> None:
        try:
            import sqlite3

            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO metabolic_needs
                    (need_id, cycle_id, kind, priority, evidence_json, estimated_cost_json,
                     risk, status, authorization_policy, success_condition, expires_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)""",
                    (
                        need.need_id,
                        cycle_id,
                        need.kind,
                        need.priority,
                        json.dumps(need.evidence),
                        json.dumps(need.estimated_cost.to_dict()),
                        need.risk,
                        need.authorization_policy,
                        need.success_condition,
                        need.expires_at,
                        datetime.now(UTC).isoformat(),
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            logger.warning("persist_need_failed: %s", exc)

    def pending(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            import sqlite3

            with sqlite3.connect(self.db_path, timeout=2) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT * FROM metabolic_needs
                    WHERE status='pending' ORDER BY priority DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
                return [dict(r) for r in rows]
        except (sqlite3.Error, OSError) as exc:
            logger.warning("pending_needs_query_failed: %s", exc)
            return []
