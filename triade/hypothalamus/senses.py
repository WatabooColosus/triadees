"""SystemSenses — Captura señales de hardware y del sistema.

Captura CPU, RAM, GPU, VRAM, disco, scheduler, errores y workers activos.
Estas señales alimentan al Hipotálamo para decisiones de regulación cognitiva.

ERRORES: logeados, nunca silenciados. Falla de sensor = señal de fallo real.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now

log = logging.getLogger(__name__)

SENSOR_FAILURE_LOG: list[dict[str, str]] = []


def _log_sensor_error(sensor_name: str, exc: Exception, details: str = "") -> None:
    entry = {
        "sensor": sensor_name,
        "error": str(exc),
        "details": details,
        "timestamp": utc_now(),
    }
    SENSOR_FAILURE_LOG.append(entry)
    if len(SENSOR_FAILURE_LOG) > 200:
        SENSOR_FAILURE_LOG.pop(0)
    log.error("SENSOR [%s] FAILED: %s %s", sensor_name, exc, details)


def _read_proc_meminfo() -> dict[str, int]:
    try:
        meminfo: dict[str, int] = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    val = int(parts[1])
                    meminfo[key] = val
        return meminfo
    except (OSError, ValueError) as exc:
        _log_sensor_error("proc_meminfo", exc)
        return {}


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    cpu_load: float = 0.0
    ram_usage: float = 0.0
    ram_total_gb: float = 0.0
    ram_used_gb: float = 0.0
    gpu_utilization: float = 0.0
    gpu_memory_used: float = 0.0
    gpu_memory_total_mb: float = 0.0
    gpu_temperature: int = 0
    disk_usage: float = 0.0
    scheduler_heartbeat_ok: bool = True
    active_workers: int = 0
    error_rate_hour: float = 0.0
    pending_tasks: int = 0
    recorded_at: str = ""
    sensor_failures: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_load": self.cpu_load,
            "ram_usage": self.ram_usage,
            "ram_total_gb": self.ram_total_gb,
            "ram_used_gb": self.ram_used_gb,
            "gpu_utilization": self.gpu_utilization,
            "gpu_memory_used": self.gpu_memory_used,
            "gpu_memory_total_mb": self.gpu_memory_total_mb,
            "gpu_temperature": self.gpu_temperature,
            "disk_usage": self.disk_usage,
            "scheduler_heartbeat_ok": self.scheduler_heartbeat_ok,
            "active_workers": self.active_workers,
            "error_rate_hour": self.error_rate_hour,
            "pending_tasks": self.pending_tasks,
            "recorded_at": self.recorded_at,
            "sensor_failures": list(self.sensor_failures),
        }


class SystemSenses:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._nvidia_cache: dict[str, Any] | None = None
        self._nvidia_cache_ts: float = 0.0

    def cpu_load(self) -> float:
        try:
            load1, _, _ = os.getloadavg()
            cpu_count = os.cpu_count() or 1
            return round(min(1.0, load1 / cpu_count), 4)
        except (OSError, AttributeError) as exc:
            _log_sensor_error("cpu_load", exc)
            return 0.0

    def ram_usage(self) -> float:
        meminfo = _read_proc_meminfo()
        if not meminfo:
            return 0.0
        total = meminfo.get("MemTotal", 1)
        available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        used = total - available
        return round(min(1.0, used / max(total, 1)), 4)

    def ram_info(self) -> tuple[float, float]:
        meminfo = _read_proc_meminfo()
        if not meminfo:
            return 0.0, 0.0
        total_kb = meminfo.get("MemTotal", 0)
        total_gb = round(total_kb / (1024 * 1024), 2)
        usage = self.ram_usage()
        used_gb = round(total_gb * usage, 2)
        return used_gb, total_gb

    def gpu_utilization(self) -> float:
        gpu_info = self._query_nvidia_smi()
        return gpu_info.get("utilization_gpu", 0.0) if gpu_info else 0.0

    def gpu_memory_used(self) -> float:
        gpu_info = self._query_nvidia_smi()
        return gpu_info.get("memory_used_ratio", 0.0) if gpu_info else 0.0

    def gpu_memory_total_mb(self) -> float:
        gpu_info = self._query_nvidia_smi()
        return gpu_info.get("memory_total_mb", 0.0) if gpu_info else 0.0

    def gpu_temperature(self) -> int:
        gpu_info = self._query_nvidia_smi()
        return gpu_info.get("temperature", 0) if gpu_info else 0

    def disk_usage(self) -> float:
        try:
            vfs = os.statvfs("/")
            total = vfs.f_blocks * vfs.f_frsize
            free = vfs.f_bavail * vfs.f_frsize
            used = total - free
            return round(min(1.0, used / max(total, 1)), 4)
        except (OSError, AttributeError) as exc:
            _log_sensor_error("disk_usage", exc)
            return 0.0

    def scheduler_heartbeat_ok(self) -> bool:
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            cols = {r[1] for r in conn.execute("PRAGMA table_info(worker_state)").fetchall()}
            if "status" not in cols or not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_state'").fetchone():
                conn.close()
                return True
            row = conn.execute(
                "SELECT status FROM worker_state WHERE key = 'scheduler_heartbeat' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row is None:
                return True
            return str(row["status"]) != "dead"
        except Exception as exc:
            _log_sensor_error("scheduler_heartbeat", exc)
            return True

    def active_workers(self) -> int:
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_tasks'").fetchone():
                conn.close()
                return 0
            cols = {r[1] for r in conn.execute("PRAGMA table_info(worker_tasks)").fetchall()}
            if "status" not in cols:
                conn.close()
                return 0
            row = conn.execute(
                "SELECT COUNT(*) as c FROM worker_tasks WHERE status = 'running'"
            ).fetchone()
            conn.close()
            return int(row["c"]) if row else 0
        except Exception as exc:
            _log_sensor_error("active_workers", exc)
            return 0

    def error_rate_hour(self) -> float:
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_events'").fetchone():
                conn.close()
                return 0.0
            cols = {r[1] for r in conn.execute("PRAGMA table_info(worker_events)").fetchall()}
            if "severity" not in cols:
                conn.close()
                return 0.0
            row = conn.execute(
                """SELECT COUNT(*) as total,
                   SUM(CASE WHEN severity IN ('error', 'critical') THEN 1 ELSE 0 END) as errors
                   FROM worker_events
                   WHERE created_at > datetime('now', '-1 hour')"""
            ).fetchone()
            conn.close()
            if row is None or int(row["total"]) == 0:
                return 0.0
            return round(int(row["errors"] or 0) / max(int(row["total"]), 1), 4)
        except Exception as exc:
            _log_sensor_error("error_rate_hour", exc)
            return 0.0

    def pending_tasks(self) -> int:
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_tasks'").fetchone():
                conn.close()
                return 0
            cols = {r[1] for r in conn.execute("PRAGMA table_info(worker_tasks)").fetchall()}
            if "status" not in cols:
                conn.close()
                return 0
            row = conn.execute(
                "SELECT COUNT(*) as c FROM worker_tasks WHERE status IN ('pending', 'queued')"
            ).fetchone()
            conn.close()
            return int(row["c"]) if row else 0
        except Exception as exc:
            _log_sensor_error("pending_tasks", exc)
            return 0

    def snapshot(self) -> SystemSnapshot:
        failures = []
        used_gb, total_gb = self.ram_info()
        try:
            cpu = self.cpu_load()
        except Exception as exc:
            _log_sensor_error("cpu_snapshot", exc)
            cpu = 0.0
            failures.append("cpu")
        try:
            ram = self.ram_usage()
        except Exception as exc:
            _log_sensor_error("ram_snapshot", exc)
            ram = 0.0
            failures.append("ram")
        try:
            gpu = self.gpu_utilization()
        except Exception as exc:
            _log_sensor_error("gpu_snapshot", exc)
            gpu = 0.0
            failures.append("gpu")
        try:
            gpu_mem = self.gpu_memory_used()
        except Exception as exc:
            _log_sensor_error("gpu_mem_snapshot", exc)
            gpu_mem = 0.0
            failures.append("gpu_mem")
        try:
            gpu_mem_total = self.gpu_memory_total_mb()
        except Exception as exc:
            _log_sensor_error("gpu_mem_total_snapshot", exc)
            gpu_mem_total = 0.0
        try:
            gpu_temp = self.gpu_temperature()
        except Exception as exc:
            _log_sensor_error("gpu_temp_snapshot", exc)
            gpu_temp = 0
            failures.append("gpu_temp")
        try:
            disk = self.disk_usage()
        except Exception as exc:
            _log_sensor_error("disk_snapshot", exc)
            disk = 0.0
            failures.append("disk")
        try:
            sched_ok = self.scheduler_heartbeat_ok()
        except Exception as exc:
            _log_sensor_error("scheduler_snapshot", exc)
            sched_ok = False
            failures.append("scheduler")
        try:
            workers = self.active_workers()
        except Exception as exc:
            _log_sensor_error("workers_snapshot", exc)
            workers = 0
            failures.append("workers")
        try:
            err_rate = self.error_rate_hour()
        except Exception as exc:
            _log_sensor_error("error_rate_snapshot", exc)
            err_rate = 0.0
            failures.append("error_rate")
        try:
            pending = self.pending_tasks()
        except Exception as exc:
            _log_sensor_error("pending_snapshot", exc)
            pending = 0
            failures.append("pending")
        return SystemSnapshot(
            cpu_load=cpu,
            ram_usage=ram,
            ram_total_gb=total_gb,
            ram_used_gb=used_gb,
            gpu_utilization=gpu,
            gpu_memory_used=gpu_mem,
            gpu_memory_total_mb=gpu_mem_total,
            gpu_temperature=gpu_temp,
            disk_usage=disk,
            scheduler_heartbeat_ok=sched_ok,
            active_workers=workers,
            error_rate_hour=err_rate,
            pending_tasks=pending,
            recorded_at=utc_now(),
            sensor_failures=tuple(failures),
        )

    def save_snapshot(self, snapshot: SystemSnapshot) -> None:
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                """CREATE TABLE IF NOT EXISTS hardware_senses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )"""
            )
            conn.execute(
                "INSERT INTO hardware_senses (snapshot_json, recorded_at) VALUES (?, ?)",
                (json.dumps(snapshot.to_dict(), ensure_ascii=False, default=str), snapshot.recorded_at),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            _log_sensor_error("save_snapshot", exc)

    def get_recent_sensor_failures(self, limit: int = 50) -> list[dict[str, str]]:
        return SENSOR_FAILURE_LOG[-limit:]

    def _query_nvidia_smi(self) -> dict[str, Any] | None:
        now = time.time()
        if self._nvidia_cache is not None and (now - self._nvidia_cache_ts) < 5.0:
            return self._nvidia_cache

        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode != 0:
                self._nvidia_cache = None
                return None
            parts = result.stdout.strip().split(", ")
            if len(parts) < 4:
                self._nvidia_cache = None
                return None
            util_gpu = float(parts[0]) / 100.0
            mem_used = float(parts[1])
            mem_total = float(parts[2])
            temp = int(float(parts[3]))
            info = {
                "utilization_gpu": round(min(1.0, util_gpu), 4),
                "memory_used_mb": mem_used,
                "memory_total_mb": mem_total,
                "memory_used_ratio": round(min(1.0, mem_used / max(mem_total, 1)), 4),
                "temperature": temp,
            }
            self._nvidia_cache = info
            self._nvidia_cache_ts = now
            return info
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, IndexError) as exc:
            _log_sensor_error("nvidia_smi", exc)
            self._nvidia_cache = None
            return None
