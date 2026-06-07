"""Dashboard de neuronas para API/UI de Tríade Ω."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .experimental_neuron_evidence import build_experimental_evidence_ledger
from .neuron_activity_store import NeuronActivityStore
from .neuron_registry import NeuronRegistry
from .stable_promotion_readiness import evaluate_stable_readiness


def build_neuron_dashboard(
    *,
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs",
    limit: int = 100,
) -> dict[str, Any]:
    """Construye estado vivo de neuronas para endpoint/UI.

    No modifica DB, no promueve, no ejecuta acciones externas.
    """
    registry = NeuronRegistry(db_path=db_path)
    neurons = registry.list_neurons(limit=limit)

    evidence = build_experimental_evidence_ledger(
        runs_dir=runs_dir,
        db_path=db_path,
        limit=limit,
        prefer_db=True,
    )
    readiness = evaluate_stable_readiness(
        runs_dir=runs_dir,
        limit=limit,
    )

    activity_store = NeuronActivityStore(db_path=db_path)
    recent_activity = activity_store.list_activity(limit=limit)

    evidence_by_name = {
        str(item.get("name")): item
        for item in evidence.get("neurons") or []
        if item.get("name")
    }
    readiness_by_name = {
        str(item.get("name")): item
        for item in readiness.get("neurons") or []
        if item.get("name")
    }

    activity_by_name: dict[str, list[dict[str, Any]]] = {}
    for row in recent_activity:
        name = str(row.get("name") or "unknown")
        activity_by_name.setdefault(name, []).append(row)

    enriched = []
    for neuron in neurons:
        name = str(neuron.get("name") or "")
        ev = evidence_by_name.get(name, {})
        rd = readiness_by_name.get(name, {})
        acts = activity_by_name.get(name, [])

        enriched.append({
            "id": neuron.get("id"),
            "name": name,
            "mission": neuron.get("mission"),
            "domain": neuron.get("domain"),
            "status": neuron.get("status"),
            "created_by": neuron.get("created_by"),
            "created_at": neuron.get("created_at"),
            "updated_at": neuron.get("updated_at"),
            "contract": {
                "rules": neuron.get("rules") or [],
                "triggers": neuron.get("triggers") or [],
                "inputs_allowed": neuron.get("inputs_allowed") or [],
                "outputs_allowed": neuron.get("outputs_allowed") or [],
                "forbidden_actions": neuron.get("forbidden_actions") or [],
                "success_metrics": neuron.get("success_metrics") or [],
                "evidence_required": neuron.get("evidence_required") or [],
                "activation_policy": neuron.get("activation_policy") or {},
                "contract_json": neuron.get("contract_json") or {},
            },
            "evidence": {
                "activation_count": ev.get("activation_count", 0),
                "diagnosis_count": ev.get("diagnosis_count", 0),
                "test_plan_count": ev.get("test_plan_count", 0),
                "last_run_id": ev.get("last_run_id"),
                "last_policy": ev.get("last_policy"),
                "source": ev.get("source"),
            },
            "readiness": {
                "ready_for_stable_review": bool(rd.get("ready_for_stable_review")),
                "blockers": rd.get("blockers", []),
                "required_human_decision": rd.get("required_human_decision", True),
            },
            "recent_activity": [
                {
                    "id": a.get("id"),
                    "run_id": a.get("run_id"),
                    "diagnosis_count": a.get("diagnosis_count"),
                    "test_plan_count": a.get("test_plan_count"),
                    "policy": a.get("policy"),
                    "created_at": a.get("created_at"),
                }
                for a in acts[:5]
            ],
            "ui_actions": allowed_ui_actions(neuron, rd),
        })

    counts: dict[str, int] = {}
    for neuron in enriched:
        status = str(neuron.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1

    return {
        "status": "ok",
        "mode": "neuron_dashboard",
        "summary": {
            "total_neurons": len(enriched),
            "by_status": counts,
            "experimental_with_evidence": (evidence.get("summary") or {}).get("experimental_neurons_with_evidence", 0),
            "ready_for_stable_review": (readiness.get("summary") or {}).get("ready_for_stable_review", 0),
        },
        "neurons": enriched,
        "policy": "dashboard_read_only_actions_require_explicit_endpoint",
    }


def allowed_ui_actions(neuron: dict[str, Any], readiness: dict[str, Any]) -> list[dict[str, Any]]:
    """Define acciones que la UI puede mostrar según estado real.

    Importante: solo describe acciones. No ejecuta nada.
    """
    status = str(neuron.get("status") or "")

    actions: list[dict[str, Any]] = []

    if status == "candidate":
        actions.extend([
            {
                "id": "approve_experimental",
                "label": "Aprobar como experimental",
                "enabled": True,
                "requires_confirmation": True,
                "endpoint": "/api/system/neurons/decision",
            },
            {
                "id": "reject",
                "label": "Rechazar",
                "enabled": True,
                "requires_confirmation": True,
                "endpoint": "/api/system/neurons/decision",
            },
            {
                "id": "request_changes",
                "label": "Pedir cambios",
                "enabled": True,
                "requires_confirmation": True,
                "endpoint": "/api/system/neurons/decision",
            },
        ])

    elif status == "experimental":
        ready = bool(readiness.get("ready_for_stable_review"))
        actions.append({
            "id": "promote_stable",
            "label": "Promover a stable",
            "enabled": ready,
            "requires_confirmation": True,
            "endpoint": "/api/system/neurons/promote-stable",
            "disabled_reason": None if ready else "Falta evidencia suficiente para revisión stable.",
        })

    elif status == "stable":
        actions.append({
            "id": "view_only",
            "label": "Stable: solo lectura",
            "enabled": False,
            "requires_confirmation": False,
            "endpoint": None,
            "disabled_reason": "Las neuronas stable no se modifican desde acciones rápidas.",
        })

    else:
        actions.append({
            "id": "view_only",
            "label": "Solo lectura",
            "enabled": False,
            "requires_confirmation": False,
            "endpoint": None,
            "disabled_reason": f"Estado no accionable: {status}",
        })

    return actions
