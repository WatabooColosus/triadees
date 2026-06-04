"""Tests del CLI de federacion de capacidades."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "triade_digimon.py"


def run_cli(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def test_federation_cli_lists_capable_nodes(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    capabilities = {
        "tier": "high",
        "cpu_count": 12,
        "ram_available_gb": 18.0,
        "gpus": [{"name": "GPU Remota", "vram_total_gb": 10.0, "cuda_available": True}],
    }

    registered = run_cli(
        "federate",
        "--db",
        str(db_path),
        "register",
        "gpu-node",
        "--name",
        "Nodo GPU",
        "--trust",
        "high",
        "--permission",
        "publish_capabilities",
        "--permission",
        "request_compute",
        "--capabilities",
        json.dumps(capabilities),
    )
    assert registered["capability_status"] == "high"

    capable = run_cli("federate", "--db", str(db_path), "capable", "--min-tier", "medium", "--require-gpu")
    assert capable["nodes"][0]["node_id"] == "gpu-node"

    doctor = run_cli("federate", "--db", str(db_path), "doctor")
    assert doctor["compute_ready_nodes"] == 1
