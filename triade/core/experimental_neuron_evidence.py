"""Ledger de evidencia para neuronas experimentales.

Resume activaciones experimentales desde artifacts de runs.
No promueve neuronas. Solo calcula evidencia observable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def build_experimental_evidence_ledger(
    runs_dir: str | Path = "runs",
    limit: int = 200,
) -> dict[str, Any]:
    runs_path = Path(runs_dir)
    run_dirs = sorted(
        [p for p in runs_path.glob("run-*") if p.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )[:limit]

    by_neuron: dict[str, dict[str, Any]] = {}

    for run_path in run_dirs:
        activity = load_json(run_path / "experimental_neuron_activity.json", {})
        if not isinstance(activity, dict) or not activity.get("active"):
            continue

        for activation in activity.get("activations") or []:
            if not isinstance(activation, dict):
                continue

            name = str(activation.get("name") or "unknown")
            output = activation.get("output") or {}
            diagnosis = output.get("diagnosis") or []
            test_plan = output.get("test_plan") or []
            policy = activation.get("policy")

            row = by_neuron.setdefault(name, {
                "name": name,
                "neuron_id": activation.get("neuron_id"),
                "status": activation.get("status"),
                "domain": activation.get("domain"),
                "activation_count": 0,
                "diagnosis_count": 0,
                "test_plan_count": 0,
                "runs": [],
                "last_run_id": None,
                "last_policy": None,
                "external_actions_allowed": False,
                "stable_promotion_ready": False,
                "promotion_blockers": [
                    "stable promotion requires separate human gate",
                    "minimum evidence threshold not evaluated yet",
                ],
            })

            row["activation_count"] += 1
            row["diagnosis_count"] += len(diagnosis) if isinstance(diagnosis, list) else 0
            row["test_plan_count"] += len(test_plan) if isinstance(test_plan, list) else 0
            row["last_run_id"] = row["last_run_id"] or run_path.name
            row["last_policy"] = policy
            row["runs"].append({
                "run_id": run_path.name,
                "match": activation.get("match"),
                "diagnosis_count": len(diagnosis) if isinstance(diagnosis, list) else 0,
                "test_plan_count": len(test_plan) if isinstance(test_plan, list) else 0,
                "policy": policy,
            })

    summary = {
        "experimental_neurons_with_evidence": len(by_neuron),
        "total_activations": sum(v["activation_count"] for v in by_neuron.values()),
        "policy": "evidence_only_no_auto_promotion",
    }

    return {
        "status": "ok",
        "mode": "experimental_neuron_evidence_ledger",
        "summary": summary,
        "neurons": sorted(by_neuron.values(), key=lambda x: x["activation_count"], reverse=True),
    }


def write_experimental_evidence_ledger(
    runs_dir: str | Path = "runs",
    out_path: str | Path = "triade/runs/experimental_neuron_evidence.json",
    limit: int = 200,
) -> dict[str, Any]:
    ledger = build_experimental_evidence_ledger(runs_dir=runs_dir, limit=limit)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return ledger
