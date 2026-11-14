"""Bounded local resource calibration for Tríade Ω.

This probe observes the existing governor and proposes a safe profile. It does
not stress the machine, install drivers, download models, or change SQLite.
"""
from __future__ import annotations

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from triade.core.resource_governor import decide_work_mode
from triade.core.resource_probe import build_resource_probe
from triade.core.ollama_blood import check_ollama_blood


def integrated_gpu_inventory() -> list[dict[str, str]]:
    if platform.system().lower() != "windows":
        return []
    try:
        p = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        data = json.loads(p.stdout or "[]")
        if isinstance(data, dict): data = [data]
        return [{"name": str(x.get("Name") or "unknown"), "driver": str(x.get("DriverVersion") or "")}
                for x in data if isinstance(x, dict)]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def calibrate() -> dict:
    probe = build_resource_probe()
    blood = check_ollama_blood()
    decision = decide_work_mode(probe, blood, requested_mode="full_local_guarded")
    limits = probe.get("limits", {})
    ram = float(limits.get("ram_available_gb") or 0)
    # Keep one model task; add a light slot only when RAM has a comfortable
    # margin and Ollama is healthy. The live worker remains the authority.
    light_slots = 2 if ram >= 6.0 and blood.get("can_reason") else 1
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": "adaptive_safe",
        "decision": decision,
        "resource_probe": probe,
        "ollama": {"blood": blood, "gpu_loaded": False},
        "windows_gpu_inventory": integrated_gpu_inventory(),
        "recommended_limits": {
            "global_tasks": light_slots,
            "model_tasks": 1,
            "read_only_tasks": light_slots,
            "serialize_model_tasks": True,
        },
        "policy": "observe_then_adjust; no driver/model download; no database mutation",
    }


if __name__ == "__main__":
    out = calibrate()
    path = REPO / "artifacts" / "audits" / "omega_adaptive_resources.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
