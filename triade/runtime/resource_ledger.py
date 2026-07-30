"""Libro contable central y política de degradación por presupuesto diario."""

from __future__ import annotations

import resource
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
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


@dataclass(frozen=True, slots=True)
class ResourceMeasurement:
    resource_name: str
    value: float | None
    unit: str
    measurement_type: str
    source: str
    started_at: str
    finished_at: str

    def __post_init__(self) -> None:
        if self.measurement_type not in {"measured", "estimated", "unavailable"}:
            raise ValueError("invalid_measurement_type")
        if self.measurement_type == "unavailable" and self.value is not None:
            raise ValueError("unavailable_measurement_cannot_have_value")
        if self.measurement_type == "measured" and not self.source:
            raise ValueError("measured_resource_requires_source")


@dataclass(frozen=True, slots=True)
class ResourceUsageReceipt:
    measurements: tuple[ResourceMeasurement, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"measurements": [asdict(item) for item in self.measurements]}

    def value(self, name: str) -> float:
        item = next((m for m in self.measurements if m.resource_name == name), None)
        return float(item.value or 0) if item else 0.0


class ResourceMeasurementCollector:
    def __init__(self) -> None:
        self.started_at = datetime.now(UTC).isoformat()
        self.started_wall = time.monotonic()
        self.self_before = resource.getrusage(resource.RUSAGE_SELF)
        self.children_before = resource.getrusage(resource.RUSAGE_CHILDREN)

    def finish(self) -> ResourceUsageReceipt:
        finished_at = datetime.now(UTC).isoformat()
        self_after = resource.getrusage(resource.RUSAGE_SELF)
        children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        measured = {
            "wall_time": (
                time.monotonic() - self.started_wall,
                "seconds",
                "time.monotonic",
            ),
            "cpu_user": (
                self_after.ru_utime
                - self.self_before.ru_utime
                + children_after.ru_utime
                - self.children_before.ru_utime,
                "seconds",
                "resource.getrusage",
            ),
            "cpu_system": (
                self_after.ru_stime
                - self.self_before.ru_stime
                + children_after.ru_stime
                - self.children_before.ru_stime,
                "seconds",
                "resource.getrusage",
            ),
            "peak_rss": (
                float(max(self_after.ru_maxrss, children_after.ru_maxrss)) / 1024,
                "MiB",
                "resource.getrusage",
            ),
        }
        items = [
            ResourceMeasurement(
                name,
                max(0.0, value),
                unit,
                "measured",
                source,
                self.started_at,
                finished_at,
            )
            for name, (value, unit, source) in measured.items()
        ]
        for name, unit in (
            ("disk_bytes_read", "bytes"),
            ("disk_bytes_written", "bytes"),
            ("network_sent", "bytes"),
            ("network_received", "bytes"),
            ("gpu_memory_peak", "MiB"),
            ("gpu_utilization", "percent"),
            ("input_tokens", "tokens"),
            ("output_tokens", "tokens"),
        ):
            items.append(
                ResourceMeasurement(
                    name,
                    None,
                    unit,
                    "unavailable",
                    "not_instrumented",
                    self.started_at,
                    finished_at,
                )
            )
        return ResourceUsageReceipt(tuple(items))


class ResourceLedger:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        budget: dict[str, float] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.budget = {**DEFAULT_BUDGET, **(budget or {})}
        migration = (
            Path(__file__).resolve().parents[1]
            / "memory/migrations/009_runtime_resilience.sql"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))
            measurements = (
                Path(__file__).resolve().parents[1]
                / "memory/migrations/018_resource_measurements.sql"
            )
            conn.executescript(measurements.read_text(encoding="utf-8"))

    def record_usage(
        self,
        *,
        task_id: str | None,
        worker_id: str | None,
        usage: ResourceUsageReceipt,
        success: bool,
        neuron_id: str | None = None,
        model: str | None = None,
        task_class: str = "general",
    ) -> int:
        entry_id = self.record(
            task_id=task_id,
            worker_id=worker_id,
            neuron_id=neuron_id,
            cpu_seconds=usage.value("cpu_user") + usage.value("cpu_system"),
            ram_peak_mb=usage.value("peak_rss"),
            duration_seconds=usage.value("wall_time"),
            model=model,
            success=success,
            task_class=task_class,
            _persist_caller_measurements=False,
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """INSERT INTO resource_measurements
                (ledger_entry_id,resource_name,value,unit,measurement_type,source,started_at,finished_at)
                VALUES(?,?,?,?,?,?,?,?)""",
                [(entry_id, *asdict(item).values()) for item in usage.measurements],
            )
        return entry_id

    def record(
        self,
        *,
        task_id: str | None,
        worker_id: str | None,
        neuron_id: str | None = None,
        cpu_seconds: float | None = None,
        gpu_seconds: float | None = None,
        ram_peak_mb: float | None = None,
        vram_peak_mb: float | None = None,
        tokens_input: int | None = None,
        tokens_output: int | None = None,
        network_bytes: int | None = None,
        disk_bytes_read: int | None = None,
        disk_bytes_written: int | None = None,
        duration_seconds: float | None = None,
        model: str | None = None,
        estimated_energy_wh: float | None = None,
        temperature_peak_c: float | None = None,
        success: bool,
        task_class: str = "general",
        _persist_caller_measurements: bool = True,
    ) -> int:
        now = datetime.now(UTC)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO resource_ledger(task_id,worker_id,neuron_id,recorded_day,cpu_seconds,gpu_seconds,
                ram_peak_mb,vram_peak_mb,tokens_input,tokens_output,network_bytes,disk_bytes_read,disk_bytes_written,
                duration_seconds,model,estimated_energy_wh,temperature_peak_c,success,task_class,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    worker_id,
                    neuron_id,
                    now.date().isoformat(),
                    max(0, cpu_seconds or 0),
                    max(0, gpu_seconds or 0),
                    max(0, ram_peak_mb or 0),
                    max(0, vram_peak_mb or 0),
                    max(0, tokens_input or 0),
                    max(0, tokens_output or 0),
                    max(0, network_bytes or 0),
                    max(0, disk_bytes_read or 0),
                    max(0, disk_bytes_written or 0),
                    max(0, duration_seconds or 0),
                    model,
                    max(0, estimated_energy_wh or 0),
                    temperature_peak_c,
                    int(success),
                    task_class,
                    now.isoformat(),
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("resource_ledger_insert_missing_id")
            entry_id = int(cursor.lastrowid or -1)
            if _persist_caller_measurements:
                caller_values = {
                    "cpu_seconds": (cpu_seconds, "seconds"),
                    "gpu_seconds": (gpu_seconds, "seconds"),
                    "ram_peak": (ram_peak_mb, "MiB"),
                    "vram_peak": (vram_peak_mb, "MiB"),
                    "input_tokens": (tokens_input, "tokens"),
                    "output_tokens": (tokens_output, "tokens"),
                    "network_bytes": (network_bytes, "bytes"),
                    "disk_bytes_read": (disk_bytes_read, "bytes"),
                    "disk_bytes_written": (disk_bytes_written, "bytes"),
                    "wall_time": (duration_seconds, "seconds"),
                    "estimated_energy": (estimated_energy_wh, "Wh"),
                    "temperature_peak": (temperature_peak_c, "celsius"),
                }
                conn.executemany(
                    """INSERT INTO resource_measurements
                    (ledger_entry_id,resource_name,value,unit,measurement_type,source,started_at,finished_at)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    [
                        (
                            entry_id,
                            name,
                            float(value),
                            unit,
                            "estimated",
                            "caller_reported",
                            now.isoformat(),
                            now.isoformat(),
                        )
                        for name, (value, unit) in caller_values.items()
                        if value is not None
                    ],
                )
            return entry_id

    def daily_usage(self, day: str | None = None) -> dict[str, float]:
        day = day or datetime.now(UTC).date().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(cpu_seconds),0),COALESCE(SUM(gpu_seconds),0),
                COALESCE(SUM(network_bytes),0),COALESCE(SUM(disk_bytes_written),0),
                COALESCE(SUM(task_class='research'),0),COALESCE(SUM(task_class='deep_evaluation'),0),
                COALESCE(SUM(task_class='model_install'),0) FROM resource_ledger WHERE recorded_day=?""",
                (day,),
            ).fetchone()
        assert row is not None
        return {
            "cpu_minutes_daily": row[0] / 60,
            "gpu_minutes_daily": row[1] / 60,
            "network_mb_daily": row[2] / 1024**2,
            "new_storage_mb_daily": row[3] / 1024**2,
            "research_tasks_daily": float(row[4]),
            "deep_evaluations_daily": float(row[5]),
            "model_installs_daily": float(row[6]),
        }

    def policy(self) -> dict[str, Any]:
        usage = self.daily_usage()
        ratios = {
            key: usage[key] / limit if limit > 0 else 1.0
            for key, limit in self.budget.items()
        }
        peak = max(ratios.values(), default=0.0)
        if peak >= 1:
            mode, allowed = "observe_only", {"heartbeat", "safety", "maintenance"}
        elif peak >= 0.95:
            mode, allowed = (
                "critical_maintenance",
                {"heartbeat", "safety", "maintenance"},
            )
        elif peak >= 0.85:
            mode, allowed = (
                "research_suspended",
                {"heartbeat", "safety", "maintenance", "light"},
            )
        elif peak >= 0.70:
            mode, allowed = (
                "cost_reduced",
                {"heartbeat", "safety", "maintenance", "light", "research"},
            )
        else:
            mode, allowed = (
                "normal",
                {
                    "heartbeat",
                    "safety",
                    "maintenance",
                    "light",
                    "research",
                    "deep_evaluation",
                    "model_install",
                },
            )
        return {
            "mode": mode,
            "peak_ratio": peak,
            "usage": usage,
            "budget": self.budget,
            "allowed_classes": sorted(allowed),
        }

    def allows(self, task_class: str) -> bool:
        return task_class in self.policy()["allowed_classes"]
