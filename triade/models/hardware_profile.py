"""Perfil de hardware local para selección de modelos.

No usa dependencias externas. En Linux lee /proc/meminfo y os.cpu_count().
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
import os


@dataclass(slots=True)
class HardwareProfile:
    cpu_count: int
    ram_total_gb: float
    ram_available_gb: float
    tier: str
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HardwareProfiler:
    """Detecta capacidad local de forma conservadora."""

    def detect(self) -> HardwareProfile:
        cpu_count = os.cpu_count() or 1
        total_kb, available_kb = self._linux_memory_kb()
        total_gb = round(total_kb / 1024 / 1024, 2) if total_kb else 0.0
        available_gb = round(available_kb / 1024 / 1024, 2) if available_kb else 0.0
        tier = self._tier(cpu_count=cpu_count, ram_total_gb=total_gb, ram_available_gb=available_gb)
        notes = [
            f"cpu_count={cpu_count}",
            f"ram_total_gb={total_gb}",
            f"ram_available_gb={available_gb}",
            f"tier={tier}",
        ]
        return HardwareProfile(
            cpu_count=cpu_count,
            ram_total_gb=total_gb,
            ram_available_gb=available_gb,
            tier=tier,
            notes=notes,
        )

    @staticmethod
    def _linux_memory_kb() -> tuple[int, int]:
        meminfo = Path("/proc/meminfo")
        if not meminfo.exists():
            return 0, 0
        values: dict[str, int] = {}
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(":")
                try:
                    values[key] = int(parts[1])
                except ValueError:
                    continue
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        return total, available

    @staticmethod
    def _tier(cpu_count: int, ram_total_gb: float, ram_available_gb: float) -> str:
        if ram_total_gb >= 24 and ram_available_gb >= 12 and cpu_count >= 8:
            return "high"
        if ram_total_gb >= 12 and ram_available_gb >= 5 and cpu_count >= 4:
            return "medium"
        return "low"
