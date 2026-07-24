"""SystemSenses — Captura señales de hardware y del sistema.

Captura CPU, RAM, GPU, VRAM, disco, scheduler, errores y workers activos.
Estas señales alimentan al Hipotálamo para decisiones de regulación cognitiva.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.contracts import utc_now


@dataclass(frozen=True, slots=True)
class SystemSnapshot:
    """Snapshot completo del estado del sistema en un momento dado."""
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
        }


class SystemSenses:
    """Captura señales del hardware y del sistema para el Hipotálamo."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    # --- Hardware ---

    def cpu_load(self) -> float:
        """Carga de CPU promedio de los últimos 1-5 segundos. Rango 0.0-1.0."""
        try:
            import os
            # os.getloadavg() retorna (1min, 5min, 15min) load averages
            load1, load5, _ = os.getloadavg()
            # Normalizar por número de CPUs
            cpu_count = os.cpu_count() or 1
            return round(min(1.0, load1 / cpu_count), 4)
        except (OSError, AttributeError):
            return 0.0

    def ram_usage(self) -> float:
        """Uso de RAM. Rango 0.0-1.0."""
        try:
            import os
            # Leer /proc/meminfo directamente
            meminfo = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        key = parts[0].rstrip(":")
                        val = int(parts[1])  # en kB
                        meminfo[key] = val
            total = meminfo.get("MemTotal", 1)
            available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            used = total - available
            return round(min(1.0, used / max(total, 1)), 4)
        except Exception:
            return 0.0

    def ram_info(self) -> tuple[float, float]:
        """Retorna (used_gb, total_gb)."""
        try:
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] == "MemTotal:":
                        total_kb = int(parts[1])
                        total_gb = round(total_kb / (1024 * 1024), 2)
                        usage = self.ram_usage()
                        used_gb = round(total_gb * usage, 2)
                        return used_gb, total_gb
        except Exception:
            pass
        return 0.0, 0.0

    def gpu_utilization(self) -> float:
        """Utilización de GPU. Rango 0.0-1.0. Retorna 0.0 si no hay GPU."""
        gpu_info = self._query_nvidia_smi()
        if gpu_info is None:
            return 0.0
        return gpu_info.get("utilization_gpu", 0.0)

    def gpu_memory_used(self) -> float:
        """Memoria GPU usada. Rango 0.0-1.0."""
        gpu_info = self._query_nvidia_smi()
        if gpu_info is None:
            return 0.0
        return gpu_info.get("memory_used_ratio", 0.0)

    def gpu_memory_total_mb(self) -> float:
        """Memoria GPU total en MB."""
        gpu_info = self._query_nvidia_smi()
        if gpu_info is None:
            return 0.0
        return gpu_info.get("memory_total_mb", 0.0)

    def gpu_temperature(self) -> int:
        """Temperatura de GPU en Celsius. Retorna 0 si no hay GPU."""
        gpu_info = self._query_nvidia_smi()
        if gpu_info is None:
            return 0
        return gpu_info.get("temperature", 0)

    def disk_usage(self) -> float:
        """Uso de disco de la partición raíz. Rango 0.0-1.0."""
        try:
            stat = Path("/").stat()
            import os
            # Usar os.statvfs si disponible
            vfs = os.statvfs("/")
            total = vfs.f_blocks * vfs.f_frsize
            free = vfs.f_bavail * vfs.f_frsize
            used = total - free
            return round(min(1.0, used / max(total, 1)), 4)
        except Exception:
            return 0.0

    # --- Scheduler / Workers ---

    def scheduler_heartbeat_ok(self) -> bool:
        """Verifica si el scheduler está respondiendo."""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT status FROM worker_state WHERE key = 'scheduler_heartbeat' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row is None:
                return True  # Sin datos, asumir OK
            return str(row["status"]) != "dead"
        except Exception:
            return True

    def active_workers(self) -> int:
        """Número de workers activos."""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT COUNT(*) as c FROM worker_tasks WHERE status = 'running'"
            ).fetchone()
            conn.close()
            return int(row["c"]) if row else 0
        except Exception:
            return 0

    def error_rate_hour(self) -> float:
        """Tasa de errores en la última hora. Rango 0.0-1.0."""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
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
        except Exception:
            return 0.0

    def pending_tasks(self) -> int:
        """Tareas pendientes en la cola."""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT COUNT(*) as c FROM worker_tasks WHERE status IN ('pending', 'queued')"
            ).fetchone()
            conn.close()
            return int(row["c"]) if row else 0
        except Exception:
            return 0

    # --- Snapshot completo ---

    def snapshot(self) -> SystemSnapshot:
        """Captura todas las señales del sistema en un solo snapshot."""
        used_gb, total_gb = self.ram_info()
        return SystemSnapshot(
            cpu_load=self.cpu_load(),
            ram_usage=self.ram_usage(),
            ram_total_gb=total_gb,
            ram_used_gb=used_gb,
            gpu_utilization=self.gpu_utilization(),
            gpu_memory_used=self.gpu_memory_used(),
            gpu_memory_total_mb=self.gpu_memory_total_mb(),
            gpu_temperature=self.gpu_temperature(),
            disk_usage=self.disk_usage(),
            scheduler_heartbeat_ok=self.scheduler_heartbeat_ok(),
            active_workers=self.active_workers(),
            error_rate_hour=self.error_rate_hour(),
            pending_tasks=self.pending_tasks(),
            recorded_at=utc_now(),
        )

    def save_snapshot(self, snapshot: SystemSnapshot) -> None:
        """Persiste el snapshot en hardware_senses."""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.db_path))
            conn.execute(
                "CREATE TABLE IF NOT EXISTS hardware_senses (id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_json TEXT NOT NULL, recorded_at TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO hardware_senses (snapshot_json, recorded_at) VALUES (?, ?)",
                (json.dumps(snapshot.to_dict(), ensure_ascii=False), snapshot.recorded_at),
            )
            conn.commit()
            conn.close()
        except Exception:
            pass

    # --- Interno ---

    _nvidia_cache: dict[str, Any] | None = None
    _nvidia_cache_ts: float = 0.0

    def _query_nvidia_smi(self) -> dict[str, Any] | None:
        """Consulta nvidia-smi con caché de 5 segundos."""
        import time
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
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError, IndexError):
            self._nvidia_cache = None
            return None
