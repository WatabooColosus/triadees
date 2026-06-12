"""Auditoría read-only de neuronas `stable`.

El objetivo no es degradar automáticamente ni borrar evidencia. El auditor solo
detecta neuronas `stable` con evidencia insuficiente y, opcionalmente, marca el
estado para revisión o las demueve a `experimental` cuando el flag explícito
`apply=True` se activa.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.experimental_neuron_evidence import build_experimental_evidence_ledger
from triade.core.neuron_activity_store import NeuronActivityStore
from triade.core.neuron_registry import NeuronRegistry
from triade.services.event_bus import publish_event


DEFAULT_THRESHOLDS = {
    "min_activations": 5,
    "min_diagnosis": 5,
    "min_test_plan": 3,
}


def audit_stable_neurons(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs",
    limit: int = 300,
    thresholds: dict[str, int] | None = None,
) -> dict[str, Any]:
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    registry = NeuronRegistry(db_path=db_path)
    stable_neurons = _list_stable_neurons(registry=registry, limit=limit)
    evidence_ledger = build_experimental_evidence_ledger(
        runs_dir=runs_dir,
        db_path=db_path,
        limit=limit,
        prefer_db=True,
    )
    evidence_by_name = {
        str(item.get("name")): item
        for item in evidence_ledger.get("neurons") or []
        if item.get("name")
    }
    activity_by_name = _activity_by_name(db_path=db_path, limit=limit)

    rows: list[dict[str, Any]] = []
    for neuron in stable_neurons:
        name = str(neuron.get("name") or "")
        evidence = evidence_by_name.get(name, {})
        activity = activity_by_name.get(name, [])
        activation_count = int(evidence.get("activation_count") or 0)
        diagnosis_count = int(evidence.get("diagnosis_count") or 0)
        test_plan_count = int(evidence.get("test_plan_count") or 0)
        activity_count = len(activity)

        blockers: list[str] = []
        if activation_count < thresholds["min_activations"]:
            blockers.append(f"activation_count {activation_count} < {thresholds['min_activations']}")
        if diagnosis_count < thresholds["min_diagnosis"]:
            blockers.append(f"diagnosis_count {diagnosis_count} < {thresholds['min_diagnosis']}")
        if test_plan_count < thresholds["min_test_plan"]:
            blockers.append(f"test_plan_count {test_plan_count} < {thresholds['min_test_plan']}")

        if blockers:
            if activation_count < 2 or diagnosis_count < 2 or test_plan_count < 1:
                recommended_action = "demote_to_experimental"
            else:
                recommended_action = "mark_needs_review"
        else:
            recommended_action = "keep_stable"

        rows.append({
            "name": name,
            "status": "stable",
            "activation_count": activation_count,
            "diagnosis_count": diagnosis_count,
            "test_plan_count": test_plan_count,
            "activity_count": activity_count,
            "blockers": blockers,
            "recommended_action": recommended_action,
            "apply_allowed": False,
            "last_run_id": evidence.get("last_run_id"),
            "last_policy": evidence.get("last_policy"),
            "evidence_source": evidence.get("source"),
        })

    total_stable = len(rows)
    with_enough = sum(1 for row in rows if row["recommended_action"] == "keep_stable")
    needs_review = total_stable - with_enough

    return {
        "status": "ok",
        "mode": "stable_neuron_audit",
        "total_stable_neurons": total_stable,
        "stable_with_enough_evidence": with_enough,
        "stable_needs_review": needs_review,
        "neurons": rows,
        "policy": {
            "read_only_by_default": True,
            "identity_core_modified": False,
            "data_deleted": False,
            "apply_requires_explicit_flag": True,
        },
        "thresholds": thresholds,
        "runs_dir": str(Path(runs_dir)),
    }


def apply_stable_neuron_audit(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs",
    limit: int = 300,
    thresholds: dict[str, int] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    report = audit_stable_neurons(
        db_path=db_path,
        runs_dir=runs_dir,
        limit=limit,
        thresholds=thresholds,
    )
    if not apply:
        report["applied"] = False
        report["applied_count"] = 0
        report["applied_changes"] = []
        return report

    registry = NeuronRegistry(db_path=db_path)
    applied_changes: list[dict[str, Any]] = []
    for neuron in report.get("neurons") or []:
        recommended_action = str(neuron.get("recommended_action") or "")
        if recommended_action == "keep_stable":
            continue
        target_status = "experimental" if recommended_action == "demote_to_experimental" else "needs_review"
        name = str(neuron.get("name") or "")
        if not name:
            continue
        updated = registry.update_status(name, target_status)
        event = publish_event(
            "stable_neuron_audit_applied",
            "stable_neuron_audit",
            {
                "name": name,
                "from_status": "stable",
                "to_status": target_status,
                "recommended_action": recommended_action,
                "blockers": neuron.get("blockers", []),
                "message": f"Stable audit applied to {name}: {target_status}.",
            },
            severity="warning" if target_status == "needs_review" else "important",
            db_path=db_path,
        )
        applied_changes.append({
            "name": name,
            "updated_status": updated.get("status"),
            "event": event,
            "recommended_action": recommended_action,
        })

    report["applied"] = True
    report["applied_count"] = len(applied_changes)
    report["applied_changes"] = applied_changes
    report["policy"]["identity_core_modified"] = False
    return report


def _activity_by_name(
    *,
    db_path: str | Path,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    store = NeuronActivityStore(db_path=db_path)
    rows = store.list_activity(limit=limit)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        name = str(row.get("name") or "")
        if not name:
            continue
        grouped.setdefault(name, []).append(row)
    return grouped


def _list_stable_neurons(*, registry: NeuronRegistry, limit: int) -> list[dict[str, Any]]:
    with registry._connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, mission, domain, rules, triggers, inputs_allowed, outputs_allowed,
                   forbidden_actions, success_metrics, evidence_required, activation_policy,
                   contract_json, status, created_by, created_at, updated_at
            FROM neurons
            WHERE status = 'stable'
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [registry._decode_neuron(dict(row)) for row in rows]
