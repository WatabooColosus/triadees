"""Auditor de preparación para promoción estable de neuronas.

No promueve neuronas. Solo evalúa si una neurona experimental tiene evidencia
suficiente y diversa para pasar a revisión humana futura.

Requisitos de evidencia diversa:
  - No basta con activaciones sintéticas (experimental_light_pulse).
  - Se requiere al menos 1 activación con policy diferente a experimental_light_pulse
    (ej: user_run, test_run, worker_task, system_pulse_continuous real).
  - Se requiere al menos 1 verificación o reporte externo del runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .experimental_neuron_evidence import build_experimental_evidence_ledger


DEFAULT_THRESHOLDS = {
    "min_activations": 5,
    "min_diagnosis": 5,
    "min_test_plan": 3,
    "min_non_synthetic_activations": 1,
    "min_external_verifications": 1,
}

SYNTHETIC_POLICIES = {"experimental_light_pulse"}


def evaluate_stable_readiness(
    runs_dir: str | Path = "runs",
    limit: int = 300,
    thresholds: dict[str, int] | None = None,
    db_path: str | Path | None = None,
    prefer_db: bool = False,
) -> dict[str, Any]:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    ledger = build_experimental_evidence_ledger(runs_dir=runs_dir, limit=limit, db_path=db_path or "triade/memory/triade.db", prefer_db=prefer_db)

    rows = []
    for neuron in ledger.get("neurons") or []:
        activation_count = int(neuron.get("activation_count") or 0)
        diagnosis_count = int(neuron.get("diagnosis_count") or 0)
        test_plan_count = int(neuron.get("test_plan_count") or 0)
        external_actions_allowed = bool(neuron.get("external_actions_allowed"))

        # Contar activaciones no sintéticas (policy distinto de experimental_light_pulse)
        runs = neuron.get("runs") or []
        non_synthetic_count = sum(
            1 for r in runs
            if str(r.get("policy") or "") not in SYNTHETIC_POLICIES
        )
        # Contar verificaciones externas (runs con run_id que no sea pulse-*)
        external_verification_count = sum(
            1 for r in runs
            if str(r.get("run_id") or "").startswith("run-")
        )

        blockers: list[str] = []

        if activation_count < thresholds["min_activations"]:
            blockers.append(f"activation_count {activation_count} < {thresholds['min_activations']}")
        if diagnosis_count < thresholds["min_diagnosis"]:
            blockers.append(f"diagnosis_count {diagnosis_count} < {thresholds['min_diagnosis']}")
        if test_plan_count < thresholds["min_test_plan"]:
            blockers.append(f"test_plan_count {test_plan_count} < {thresholds['min_test_plan']}")
        if external_actions_allowed:
            blockers.append("external_actions_allowed must be false")
        if str(neuron.get("status")) != "experimental":
            blockers.append("neuron status must be experimental")
        if non_synthetic_count < thresholds["min_non_synthetic_activations"]:
            blockers.append(
                f"non_synthetic_activations {non_synthetic_count} < {thresholds['min_non_synthetic_activations']} "
                f"(requires evidence from user runs, tests, or workers — not only experimental_light_pulse)"
            )
        if external_verification_count < thresholds["min_external_verifications"]:
            blockers.append(
                f"external_verifications {external_verification_count} < {thresholds['min_external_verifications']} "
                f"(requires at least 1 run-* artifact as evidence)"
            )

        ready = not blockers

        rows.append({
            "name": neuron.get("name"),
            "neuron_id": neuron.get("neuron_id"),
            "status": neuron.get("status"),
            "domain": neuron.get("domain"),
            "ready_for_stable_review": ready,
            "activation_count": activation_count,
            "diagnosis_count": diagnosis_count,
            "test_plan_count": test_plan_count,
            "non_synthetic_activations": non_synthetic_count,
            "external_verifications": external_verification_count,
            "last_run_id": neuron.get("last_run_id"),
            "blockers": blockers,
            "required_human_decision": True,
            "policy": "readiness_only_no_auto_stable",
        })

    summary = {
        "neurons_evaluated": len(rows),
        "ready_for_stable_review": sum(1 for r in rows if r["ready_for_stable_review"]),
        "not_ready": sum(1 for r in rows if not r["ready_for_stable_review"]),
        "thresholds": thresholds,
        "policy": "readiness_only_no_auto_stable",
    }

    return {
        "status": "ok",
        "mode": "stable_promotion_readiness",
        "summary": summary,
        "neurons": rows,
    }


def write_stable_readiness_report(
    runs_dir: str | Path = "runs",
    out_path: str | Path = "triade/runs/stable_promotion_readiness.json",
    limit: int = 300,
    thresholds: dict[str, int] | None = None,
) -> dict[str, Any]:
    report = evaluate_stable_readiness(runs_dir=runs_dir, limit=limit, thresholds=thresholds)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
