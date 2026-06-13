"""Resource Probe · lectura segura de hardware, energía y carga del sistema."""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path
from typing import Any


def _linux_load_avg() -> dict[str, Any]:
    try:
        text = Path("/proc/loadavg").read_text(encoding="utf-8", errors="ignore").strip()
        parts = text.split()
        if len(parts) >= 3:
            return {
                "load_1min": float(parts[0]),
                "load_5min": float(parts[1]),
                "load_15min": float(parts[2]),
                "running_processes": parts[3] if len(parts) > 3 else None,
            }
    except (OSError, ValueError):
        pass
    return {"load_1min": None, "load_5min": None, "load_15min": None}


def _linux_power() -> dict[str, Any]:
    power_supply = Path("/sys/class/power_supply")
    if not power_supply.is_dir():
        return {"ac_connected": None, "battery_percent": None, "battery_status": None, "power_source": None}
    ac_connected = None
    battery_percent = None
    battery_status = None
    power_source = None
    for entry in power_supply.iterdir():
        try:
            type_file = entry / "type"
            if not type_file.exists():
                continue
            ptype = type_file.read_text(encoding="utf-8", errors="ignore").strip()
            if ptype == "Mains":
                online = (entry / "online").read_text(encoding="utf-8", errors="ignore").strip()
                ac_connected = online == "1"
                if ac_connected:
                    power_source = "AC"
            elif ptype == "Battery":
                capacity = entry / "capacity"
                status_file = entry / "status"
                if capacity.exists():
                    battery_percent = float(capacity.read_text(encoding="utf-8", errors="ignore").strip())
                if status_file.exists():
                    battery_status = status_file.read_text(encoding="utf-8", errors="ignore").strip()
                if power_source is None:
                    if battery_status == "Discharging":
                        power_source = "battery"
                    elif battery_status == "Charging":
                        power_source = "AC"
                    else:
                        power_source = battery_status.lower() if battery_status else "unknown"
        except (OSError, ValueError):
            continue
    return {
        "ac_connected": ac_connected,
        "battery_percent": battery_percent,
        "battery_status": battery_status,
        "power_source": power_source or "unknown",
    }


def _linux_thermal() -> dict[str, Any]:
    thermal_zones = Path("/sys/class/thermal")
    if not thermal_zones.is_dir():
        return {"thermal_status": None, "temperature_celsius": None}
    temps: list[float] = []
    for entry in sorted(thermal_zones.iterdir()):
        if not entry.name.startswith("thermal_zone"):
            continue
        temp_file = entry / "temp"
        if temp_file.exists():
            try:
                raw = temp_file.read_text(encoding="utf-8", errors="ignore").strip()
                celsius = float(raw) / 1000.0
                if 0 < celsius < 120:
                    temps.append(celsius)
            except (OSError, ValueError):
                continue
    if temps:
        avg = round(sum(temps) / len(temps), 1)
        max_temp = max(temps)
        status = "ok" if max_temp < 85 else "high" if max_temp < 95 else "critical"
        return {"thermal_status": status, "temperature_celsius": avg}
    return {"thermal_status": None, "temperature_celsius": None}


def _linux_disk_free() -> tuple[float, float]:
    try:
        usage = shutil.disk_usage(".")
        return round(usage.total / 1024**3, 2), round(usage.free / 1024**3, 2)
    except OSError:
        return 0.0, 0.0


def build_resource_probe() -> dict[str, Any]:
    """Lee de forma segura hardware, energía, carga y temperatura.

    Sin shell=True. Sin comandos del usuario. Fallback seguro.
    """
    from triade.models.hardware_profile import HardwareProfiler

    warnings: list[str] = []

    # Hardware
    hw = HardwareProfiler().detect()
    hw_dict = hw.to_dict() if hasattr(hw, "to_dict") else {}

    # CPU
    cpu_count = os.cpu_count() or 1
    load = _linux_load_avg() if platform.system().lower() == "linux" else {"load_1min": None}

    # Memory
    ram_total_gb = hw_dict.get("ram_total_gb", 0.0)
    ram_available_gb = hw_dict.get("ram_available_gb", 0.0)
    mem_pct = round((1 - ram_available_gb / max(ram_total_gb, 1)) * 100, 1) if ram_total_gb > 0 else None

    # Disk
    disk_total, disk_free = _linux_disk_free()

    # GPU
    gpus_raw = hw_dict.get("gpus", [])
    gpu_info = {
        "count": len(gpus_raw),
        "devices": [{"name": g.get("name", "unknown"), "vram_gb": g.get("vram_total_gb", 0.0), "vendor": g.get("vendor", "unknown")} for g in gpus_raw],
        "total_vram_gb": round(sum(g.get("vram_total_gb", 0.0) for g in gpus_raw), 2),
    }

    # Power
    power = _linux_power() if platform.system().lower() == "linux" else {"ac_connected": None, "battery_percent": None, "power_source": "unknown"}

    # Thermal
    thermal = _linux_thermal() if platform.system().lower() == "linux" else {"thermal_status": None, "temperature_celsius": None}

    # Limits
    limits = {
        "ram_available_gb": ram_available_gb,
        "disk_free_gb": disk_free,
        "cpu_count": cpu_count,
        "tier": hw_dict.get("tier", "unknown"),
    }

    if ram_available_gb < 2:
        warnings.append(f"RAM disponible baja ({ram_available_gb} GB).")
    if disk_free < 2:
        warnings.append(f"Disco libre bajo ({disk_free} GB).")
    if power.get("battery_percent") is not None and power.get("battery_percent", 100) < 25 and not power.get("ac_connected"):
        warnings.append(f"Batería baja ({power['battery_percent']}%) sin AC.")
    if load.get("load_1min") is not None and cpu_count and load["load_1min"] > cpu_count * 2:
        warnings.append(f"Load average alto ({load['load_1min']}) para {cpu_count} CPUs.")
    if thermal.get("thermal_status") == "critical":
        warnings.append(f"Temperatura crítica ({thermal.get('temperature_celsius')}°C).")
    if thermal.get("thermal_status") == "high":
        warnings.append(f"Temperatura elevada ({thermal.get('temperature_celsius')}°C).")

    return {
        "status": "ok",
        "generated_at": __import__("datetime").datetime.now().__str__(),
        "hardware": {
            "os": hw_dict.get("os_name"),
            "tier": hw_dict.get("tier"),
            "capability_status": hw_dict.get("capability_status"),
            "notes": hw_dict.get("notes", []),
        },
        "cpu": {
            "count": cpu_count,
            "physical_cores": hw_dict.get("cpu_physical_cores", 0),
            "load_1min": load.get("load_1min"),
            "load_5min": load.get("load_5min"),
            "load_15min": load.get("load_15min"),
        },
        "memory": {
            "total_gb": ram_total_gb,
            "available_gb": ram_available_gb,
            "used_percent": mem_pct,
        },
        "disk": {
            "total_gb": disk_total,
            "free_gb": disk_free,
        },
        "gpu": gpu_info,
        "power": power,
        "thermal": thermal,
        "limits": limits,
        "warnings": warnings,
    }
