"""Ledger de evidencia para neuronas experimentales.

Prioridad de lectura:
1. SQLite `neuron_activity` para actividad persistida.
2. Fallback a artifacts `runs/*/experimental_neuron_activity.json`.

No promueve neuronas. Solo calcula evidencia observable.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .neuron_activity_store import NeuronActivityStore


def load_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _empty_row(name: str, source: str) -> dict[str, Any]:
    return {
        "name": name,
        "neuron_id": None,
        "status": None,
        "domain": None,
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
        "source": source,
    }


def _build_from_db(db_path: str | Path, limit: int = 300) -> dict[str, Any]:
    rows = NeuronActivityStore(db_path=db_path).list_activity(limit=limit)
    by_neuron: dict[str, dict[str, Any]] = {}

    for row in rows:
        name = str(row.get("name") or "unknown")
        item = by_neuron.setdefault(name, _empty_row(name, "db"))

        item["neuron_id"] = item["neuron_id"] or row.get("neuron_id")
        item["status"] = item["status"] or row.get("status")
        item["domain"] = item["domain"] or row.get("domain")
        item["activation_count"] += 1 if row.get("activated") else 0
        item["diagnosis_count"] += int(row.get("diagnosis_count") or 0)
        item["test_plan_count"] += int(row.get("test_plan_count") or 0)
        item["last_run_id"] = item["last_run_id"] or row.get("run_id")
        item["last_policy"] = item["last_policy"] or row.get("policy")
        item["runs"].append({
            "run_id": row.get("run_id"),
            "diagnosis_count": int(row.get("diagnosis_count") or 0),
            "test_plan_count": int(row.get("test_plan_count") or 0),
            "policy": row.get("policy"),
            "activity_id": row.get("id"),
        })

    summary = {
        "experimental_neurons_with_evidence": len(by_neuron),
        "total_activations": sum(v["activation_count"] for v in by_neuron.values()),
        "policy": "evidence_only_no_auto_promotion",
        "source": "db",
    }

    return {
        "status": "ok",
        "mode": "experimental_neuron_evidence_ledger",
        "summary": summary,
        "neurons": sorted(by_neuron.values(), key=lambda x: x["activation_count"], reverse=True),
    }


def _build_from_artifacts(runs_dir: str | Path = "runs", limit: int = 200) -> dict[str, Any]:
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
            output = activation.get("output") or activation.get("contribution") or {}
            diagnosis = output.get("diagnosis") or []
            test_plan = output.get("test_plan") or []
            policy = activation.get("policy")

            row = by_neuron.setdefault(name, _empty_row(name, "artifacts"))
            row["neuron_id"] = row["neuron_id"] or activation.get("neuron_id")
            row["status"] = row["status"] or activation.get("status")
            row["domain"] = row["domain"] or activation.get("domain")
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
        "source": "artifacts",
    }

    return {
        "status": "ok",
        "mode": "experimental_neuron_evidence_ledger",
        "summary": summary,
        "neurons": sorted(by_neuron.values(), key=lambda x: x["activation_count"], reverse=True),
    }


def build_experimental_evidence_ledger(
    runs_dir: str | Path = "runs",
    limit: int = 200,
    db_path: str | Path = "triade/memory/triade.db",
    prefer_db: bool = True,
) -> dict[str, Any]:
    if prefer_db:
        try:
            ledger = _build_from_db(db_path=db_path, limit=limit)
            if ledger.get("neurons"):
                return ledger
        except Exception:
            # Fallback silencioso: el ledger no debe romper el pulso vivo.
            pass

    ledger = _build_from_artifacts(runs_dir=runs_dir, limit=limit)
    if ledger.get("summary") is not None:
        ledger["summary"]["source"] = ledger["summary"].get("source", "artifacts")
    return ledger


def write_experimental_evidence_ledger(
    runs_dir: str | Path = "runs",
    out_path: str | Path = "triade/runs/experimental_neuron_evidence.json",
    limit: int = 200,
    db_path: str | Path = "triade/memory/triade.db",
    prefer_db: bool = True,
) -> dict[str, Any]:
    ledger = build_experimental_evidence_ledger(
        runs_dir=runs_dir,
        limit=limit,
        db_path=db_path,
        prefer_db=prefer_db,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    return ledger
