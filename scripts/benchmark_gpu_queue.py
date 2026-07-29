"""Snapshot no destructivo de GPU para fijar el baseline de la futura cola."""

from __future__ import annotations

import json
import subprocess


def snapshot() -> dict[str, object]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,memory.free,temperature.gpu,driver_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=5, check=True
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return {"status": "unavailable", "error": str(exc)}
    values = [item.strip() for item in completed.stdout.strip().split(",")]
    if len(values) != 6:
        return {"status": "degraded", "raw": completed.stdout.strip()}
    return {
        "status": "ok",
        "gpu": values[0],
        "vram_total_mb": float(values[1]),
        "vram_used_mb": float(values[2]),
        "vram_free_mb": float(values[3]),
        "temperature_c": float(values[4]),
        "driver": values[5],
        "note": "measurement_only_no_reservation_manager_yet",
    }


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2))
