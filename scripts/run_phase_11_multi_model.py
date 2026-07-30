#!/usr/bin/env python3
"""Audita disponibilidad real y evita adoptar routing sin A/B real."""

import json
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from triade.models.measured_orchestration import MeasuredModelOrchestrator


def installed_models() -> tuple[list[str], str | None]:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:11434/api/tags", timeout=2
        ) as response:
            payload = json.loads(response.read())
        return [item["name"] for item in payload.get("models", [])], None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return [], f"{type(exc).__name__}: {exc}"


def main() -> int:
    models, error = installed_models()
    with tempfile.TemporaryDirectory() as directory:
        orchestrator = MeasuredModelOrchestrator(Path(directory) / "triade.db", [])
        decision = orchestrator.evaluate_adoption(
            baseline_model="single-model-baseline",
            routes=[],
            baseline_metrics=None,
            candidate_metrics=None,
        )
    report = {
        "phase": 11,
        "ollama_models": models,
        "provider_error": error,
        "real_ab_executed": False,
        "routing_adopted": decision["adopted"],
        "rollback_ref": decision["rollback_ref"],
        "implementation_complete": True,
        "runtime_verified": False,
        "status": "partial",
        "reason": "real_models_unavailable" if not models else "real_ab_pending",
    }
    output = Path("artifacts/triade_verify/phase_11/multi_model.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
