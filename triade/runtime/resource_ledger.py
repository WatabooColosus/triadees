"""Libro contable central y política de degradación por presupuesto diario."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BUDGET = {
    "cpu_minutes_daily": 600.0,
    "gpu_minutes_daily": 360.0,
    "network_mb_daily": 1500.0,
    "new_storage_mb_daily": 500.0,
    "research_tasks_daily": 40.0,
    "deep_evaluations_daily": 12.0,
    "model_installs_daily": 1.0,
}


class ResourceLedger:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db", budget: dict[str, float] | None = None) -> None:
        self.db_path = Path(db_path)
        self.budget = {**DEFAULT_BUDGET, **(budget or {})}
        migration = Path(__file__).resolve().parents[1] / "memory/migrations/009_runtime_resilience.sql"
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))

    def record(self, *, task_id: str | None, worker_id: str | None, neuron_id: str | None = None,
               cpu_seconds: float = 0, gpu_seconds: float = 0, ram_peak_mb: float = 0,
               vram_peak_mb: float = 0, tokens_input: int = 0, tokens_output: int = 0,
               network_bytes: int = 0, disk_bytes_read: int = 0, disk_bytes_written: int = 0,
               duration_seconds: float = 0, model: str | None = None, estimated_energy_wh: float = 0,
               temperature_peak_c: float | None = None, success: bool, task_class: str = "general") -> int:
        now = datetime.now(timezone.utc)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO resource_ledger(task_id,worker_id,neuron_id,recorded_day,cpu_seconds,gpu_seconds,
                ram_peak_mb,vram_peak_mb,tokens_input,tokens_output,network_bytes,disk_bytes_read,disk_bytes_written,
                duration_seconds,model,estimated_energy_wh,temperature_peak_c,success,task_class,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task_id, worker_id, neuron_id, now.date().isoformat(), max(0, cpu_seconds), max(0, gpu_seconds),
                 max(0, ram_peak_mb), max(0, vram_peak_mb), max(0, tokens_input), max(0, tokens_output),
                 max(0, network_bytes), max(0, disk_bytes_read), max(0, disk_bytes_written), max(0, duration_seconds),
                 model, max(0, estimated_energy_wh), temperature_peak_c, int(success), task_class, now.isoformat()),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("resource_ledger_insert_missing_id")
            return int(cursor.lastrowid)

    def daily_usage(self, day: str | None = None) -> dict[str, float]:
        day = day or datetime.now(timezone.utc).date().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(cpu_seconds),0),COALESCE(SUM(gpu_seconds),0),
                COALESCE(SUM(network_bytes),0),COALESCE(SUM(disk_bytes_written),0),
                COALESCE(SUM(task_class='research'),0),COALESCE(SUM(task_class='deep_evaluation'),0),
                COALESCE(SUM(task_class='model_install'),0) FROM resource_ledger WHERE recorded_day=?""",
                (day,),
            ).fetchone()
        assert row is not None
        return {"cpu_minutes_daily": row[0] / 60, "gpu_minutes_daily": row[1] / 60,
                "network_mb_daily": row[2] / 1024**2, "new_storage_mb_daily": row[3] / 1024**2,
                "research_tasks_daily": float(row[4]), "deep_evaluations_daily": float(row[5]),
                "model_installs_daily": float(row[6])}

    def policy(self) -> dict[str, Any]:
        usage = self.daily_usage()
        ratios = {key: usage[key] / limit if limit > 0 else 1.0 for key, limit in self.budget.items()}
        peak = max(ratios.values(), default=0.0)
        if peak >= 1:
            mode, allowed = "observe_only", {"heartbeat", "safety", "maintenance"}
        elif peak >= 0.95:
            mode, allowed = "critical_maintenance", {"heartbeat", "safety", "maintenance"}
        elif peak >= 0.85:
            mode, allowed = "research_suspended", {"heartbeat", "safety", "maintenance", "light"}
        elif peak >= 0.70:
            mode, allowed = "cost_reduced", {"heartbeat", "safety", "maintenance", "light", "research"}
        else:
            mode, allowed = "normal", {"heartbeat", "safety", "maintenance", "light", "research", "deep_evaluation", "model_install"}
        return {"mode": mode, "peak_ratio": peak, "usage": usage, "budget": self.budget, "allowed_classes": sorted(allowed)}

    def allows(self, task_class: str) -> bool:
        return task_class in self.policy()["allowed_classes"]
