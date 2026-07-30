from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from triade.metabolism.contracts import ResourceBudget

logger = logging.getLogger(__name__)


class BudgetTracker:
    PER_CYCLE_LIMITS = {
        "cpu_seconds": 30.0,
        "ram_mb": 512.0,
        "disk_read_mb": 10.0,
        "disk_write_mb": 5.0,
        "duration_seconds": 60.0,
        "needs_count": 10,
    }

    HOURLY_LIMITS = {
        "cpu_seconds": 300.0,
        "disk_read_mb": 100.0,
        "disk_write_mb": 50.0,
    }

    DAILY_LIMITS = {
        "cpu_seconds": 3600.0,
        "disk_read_mb": 500.0,
        "disk_write_mb": 250.0,
    }

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def check_cycle_budget(
        self, cycle_id: int, estimated: ResourceBudget
    ) -> tuple[bool, str]:
        used = self._cycle_usage(cycle_id)
        if used["needs_count"] >= self.PER_CYCLE_LIMITS["needs_count"]:
            return False, "max_needs_per_cycle_exceeded"
        if estimated.cpu_seconds_max > self.PER_CYCLE_LIMITS["cpu_seconds"]:
            return False, "cpu_budget_exceeds_cycle_limit"
        if estimated.ram_mb_max > self.PER_CYCLE_LIMITS["ram_mb"]:
            return False, "ram_budget_exceeds_cycle_limit"
        if estimated.duration_seconds_max > self.PER_CYCLE_LIMITS["duration_seconds"]:
            return False, "duration_budget_exceeds_cycle_limit"
        return True, ""

    def check_global_budget(self, kind: str) -> tuple[bool, str]:
        now = time.time()
        hourly = self._period_usage(kind, now - 3600)
        daily = self._period_usage(kind, now - 86400)

        limits = {
            "cpu_seconds": (self.HOURLY_LIMITS["cpu_seconds"], self.DAILY_LIMITS["cpu_seconds"]),
        }
        if kind in limits:
            h_limit, d_limit = limits[kind]
            if hourly >= h_limit:
                return False, f"hourly_limit_reached_for_{kind}"
            if daily >= d_limit:
                return False, f"daily_limit_reached_for_{kind}"
        return True, ""

    def _cycle_usage(self, cycle_id: int) -> dict[str, float]:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                row = conn.execute(
                    """SELECT COUNT(*) as needs_count,
                    COALESCE(SUM(cpu_seconds),0) as cpu_seconds,
                    COALESCE(SUM(ram_mb),0) as ram_mb
                    FROM metabolic_receipts WHERE cycle_id=?""",
                    (cycle_id,),
                ).fetchone()
                if row:
                    return {
                        "needs_count": int(row[0]),
                        "cpu_seconds": float(row[1]),
                        "ram_mb": float(row[2]),
                    }
        except (sqlite3.Error, OSError) as exc:
            logger.warning("cycle_usage_query_failed: %s", exc)
        return {"needs_count": 0, "cpu_seconds": 0.0, "ram_mb": 0.0}

    def _period_usage(self, kind: str, since: float) -> float:
        try:
            with sqlite3.connect(self.db_path, timeout=2) as conn:
                since_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(since))
                row = conn.execute(
                    """SELECT COALESCE(SUM(cpu_seconds),0) FROM metabolic_receipts r
                    JOIN metabolic_needs n ON r.need_id=n.need_id
                    WHERE n.kind=? AND r.started_at>=?""",
                    (kind, since_iso),
                ).fetchone()
                return float(row[0]) if row else 0.0
        except (sqlite3.Error, OSError) as exc:
            logger.warning("period_usage_query_failed: %s", exc)
            return 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "per_cycle_limits": dict(self.PER_CYCLE_LIMITS),
            "hourly_limits": dict(self.HOURLY_LIMITS),
            "daily_limits": dict(self.DAILY_LIMITS),
        }
