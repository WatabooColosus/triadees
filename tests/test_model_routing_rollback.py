from __future__ import annotations

import json
from pathlib import Path

from scripts.rollback_phase_11_model_routing import rollback_routing


def test_measured_routing_rollback_restores_baseline_atomically(tmp_path: Path) -> None:
    active = tmp_path / "active.json"
    rollback = tmp_path / "rollback.json"
    active.write_text(
        json.dumps({"status": "active", "routes": {"coder": "candidate"}}),
        encoding="utf-8",
    )
    rollback.write_text(
        json.dumps(
            {
                "status": "rollback_baseline",
                "routes": {"coder": "single-model"},
            }
        ),
        encoding="utf-8",
    )

    result = rollback_routing(active, rollback)

    restored = json.loads(active.read_text(encoding="utf-8"))
    assert result["status"] == "rolled_back"
    assert restored["status"] == "rollback_baseline"
    assert restored["routes"] == {"coder": "single-model"}
