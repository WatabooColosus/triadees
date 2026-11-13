"""Bounded, read-only accelerator telemetry; VRAM is not host RAM."""

import csv
import io
import shutil
import subprocess
from datetime import UTC, datetime


def probe_nvidia() -> dict:
    executable = shutil.which("nvidia-smi")
    unavailable = {"status": "unavailable", "devices": []}
    if not executable:
        return unavailable
    try:
        result = subprocess.run(
            [
                executable,
                "--query-gpu=uuid,memory.total,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        devices = []
        for row in csv.reader(io.StringIO(result.stdout)):
            if len(row) != 5:
                return unavailable
            values = []
            for value in row[1:]:
                try:
                    number = float(value.strip())
                    values.append(number if 0 <= number < float("inf") else None)
                except ValueError:
                    values.append(None)
            devices.append(
                dict(
                    zip(
                        (
                            "uuid",
                            "total_mib",
                            "free_mib",
                            "utilization_percent",
                            "temperature_celsius",
                        ),
                        [row[0].strip(), *values],
                    )
                )
            )
        return {
            "status": "ok" if devices else "unavailable",
            "devices": devices,
            "observed_at": datetime.now(UTC).isoformat(),
        }
    except (OSError, subprocess.SubprocessError):
        return unavailable


def probe_battery() -> dict:
    unknown = {"ac_connected": None, "battery_percent": None, "power_source": "unknown"}
    try:
        import psutil

        battery = psutil.sensors_battery()
        if battery is None:
            return unknown
        return {
            "ac_connected": battery.power_plugged,
            "battery_percent": battery.percent,
            "power_source": "AC" if battery.power_plugged else "battery",
        }
    except (ImportError, AttributeError, OSError, RuntimeError):
        return unknown
