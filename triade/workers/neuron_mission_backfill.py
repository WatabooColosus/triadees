"""Backfill seguro de misiones neuronales desde neuronas ya existentes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.neuron_activity_store import NeuronActivityStore
from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
from triade.core.neuron_registry import NeuronRegistry
from triade.core.stable_promotion_readiness import evaluate_stable_readiness


SAFE_ALLOWED_SOURCES = ["worker", "runs", "qualia_bus", "neuron_activity"]
SAFE_ALLOWED_ACTIONS = ["observe", "diagnose", "propose_learning"]
SAFE_STABLE_ACTIONS = [*SAFE_ALLOWED_ACTIONS, "request_stable_promotion"]
ACTIVE_NEURON_STATUSES = {"experimental", "stable"}


def build_neuron_mission_contract(neuron: dict[str, Any], mission_status: str, ready_for_stable_review: bool) -> NeuronMission:
    name = str(neuron.get("name") or f"neuron-{neuron.get('id') or 'unknown'}").strip()
    mission_text = str(neuron.get("mission") or "").strip() or f"Trabajar la neurona {name} con evidencia local."
    domain = str(neuron.get("domain") or "general").strip() or "general"
    status = "stable" if mission_status == "stable" and ready_for_stable_review else "experimental"
    allowed_actions = SAFE_STABLE_ACTIONS if status == "stable" else SAFE_ALLOWED_ACTIONS
    return NeuronMission(
        neuron_id=int(neuron.get("id")) if neuron.get("id") is not None else None,
        title=name,
        mission=mission_text,
        domain=domain,
        allowed_sources=list(SAFE_ALLOWED_SOURCES),
        allowed_actions=list(dict.fromkeys(allowed_actions)),
        schedule_hint="every_cycle",
        status=status,
        metrics={
            "backfilled_from_neuron": name,
            "backfilled_from_neuron_status": str(neuron.get("status") or "unknown"),
            "ready_for_stable_review": ready_for_stable_review,
        },
    )


def _stable_mission_ready(
    *,
    neuron: dict[str, Any],
    registry: NeuronRegistry,
    activity_store: NeuronActivityStore,
    readiness_by_name: dict[str, dict[str, Any]],
) -> tuple[bool, dict[str, Any]]:
    name = str(neuron.get("name") or "")
    neuron_id = int(neuron.get("id") or 0)
    training_count = len(registry.list_training(neuron_id, limit=20)) if neuron_id else 0
    activity_count = len(activity_store.list_activity(name=name, limit=20)) if name else 0
    readiness = readiness_by_name.get(name) or {}
    ready_for_stable_review = bool(readiness.get("ready_for_stable_review"))
    ready = bool(
        str(neuron.get("status")) == "stable"
        and (training_count > 0 or activity_count > 0)
        and (ready_for_stable_review or (training_count + activity_count) >= 2)
    )
    return ready, {
        "training_count": training_count,
        "activity_count": activity_count,
        "ready_for_stable_review": ready_for_stable_review,
    }


def backfill_neuron_missions(
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs",
    limit: int = 500,
) -> dict[str, Any]:
    registry = NeuronRegistry(db_path=db_path)
    store = NeuronMissionStore(db_path=db_path)
    activity_store = NeuronActivityStore(db_path=db_path)
    neurons = [
        neuron
        for neuron in registry.list_neurons(limit=limit)
        if str(neuron.get("status") or "") in ACTIVE_NEURON_STATUSES
    ]
    readiness = evaluate_stable_readiness(runs_dir=runs_dir, limit=limit, db_path=db_path, prefer_db=True)
    readiness_by_name = {
        str(item.get("name")): item
        for item in readiness.get("neurons") or []
        if item.get("name")
    }

    created: list[dict[str, Any]] = []
    skipped_existing: list[dict[str, Any]] = []
    skipped_ineligible: list[dict[str, Any]] = []

    for neuron in neurons:
        name = str(neuron.get("name") or "")
        existing = store.get_missions_by_neuron(int(neuron["id"]))
        if existing:
            skipped_existing.append({
                "neuron_id": neuron.get("id"),
                "name": name,
                "existing_missions": len(existing),
            })
            continue

        ready_for_stable, stable_metrics = _stable_mission_ready(
            neuron=neuron,
            registry=registry,
            activity_store=activity_store,
            readiness_by_name=readiness_by_name,
        )
        target_status = "stable" if ready_for_stable else "experimental"

        mission = build_neuron_mission_contract(neuron, target_status, ready_for_stable)
        mission.metrics.update({
            "training_count": stable_metrics["training_count"],
            "activity_count": stable_metrics["activity_count"],
            "ready_for_stable_review": stable_metrics["ready_for_stable_review"],
        })
        mission_id = store.create_mission(mission)
        created.append(store.get_mission(mission_id).to_dict() if store.get_mission(mission_id) else {"id": mission_id})

    if not neurons:
        skipped_ineligible.append({"reason": "no_experimental_or_stable_neurons_found"})

    return {
        "status": "ok",
        "mode": "neuron_mission_backfill",
        "created_count": len(created),
        "skipped_existing_count": len(skipped_existing),
        "skipped_ineligible_count": len(skipped_ineligible),
        "created": created,
        "skipped_existing": skipped_existing,
        "skipped_ineligible": skipped_ineligible,
        "policy": {
            "identity_core_modified": False,
            "stable_memory_written": False,
            "shell": False,
            "network": False,
            "dangerous_actions_blocked": [
                "modify_identity_core",
                "write_stable_memory",
                "shell",
                "network",
                "bypass_safety",
                "self_approve",
            ],
        },
    }


def neuron_missions_doctor(
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs",
    limit: int = 500,
) -> dict[str, Any]:
    store = NeuronMissionStore(db_path=db_path)
    registry = NeuronRegistry(db_path=db_path)
    missions = store.list_missions(limit=limit)
    cycles_by_mission = {int(m.id): store.list_cycles(int(m.id), limit=1) for m in missions if m.id is not None}
    evidence_by_mission = {int(m.id): store.list_evidence(int(m.id), limit=1) for m in missions if m.id is not None}
    ready_to_execute = [m for m in missions if m.status in {"experimental", "stable"}]

    learning_candidates: list[dict[str, Any]] = []
    try:
        import sqlite3

        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT candidate_id, source_ref, title, domain, status, confidence, utility, updated_at
                FROM learning_queue
                WHERE source_ref LIKE 'mission:%'
                ORDER BY updated_at DESC, id DESC
                LIMIT ?""",
                (limit,),
            ).fetchall()
            learning_candidates = [dict(row) for row in rows]
    except Exception:
        learning_candidates = []

    missions_by_status: dict[str, int] = {}
    missions_without_cycles = 0
    missions_with_evidence = 0
    for mission in missions:
        status = str(mission.status or "unknown")
        missions_by_status[status] = missions_by_status.get(status, 0) + 1
        if not cycles_by_mission.get(int(mission.id or 0)):
            missions_without_cycles += 1
        if evidence_by_mission.get(int(mission.id or 0)):
            missions_with_evidence += 1

    return {
        "status": "ok",
        "mode": "neuron_missions_doctor",
        "total_neurons": len(registry.list_neurons(limit=limit)),
        "total_missions": len(missions),
        "missions_by_status": missions_by_status,
        "missions_without_cycles": missions_without_cycles,
        "missions_with_evidence": missions_with_evidence,
        "mission_learning_candidates": len(learning_candidates),
        "ready_to_execute_count": len(ready_to_execute),
        "missions": [m.to_dict() for m in missions],
        "learning_candidates": learning_candidates,
        "policy": {
            "identity_core_protected": True,
            "stable_memory_written": False,
            "shell": False,
            "network": False,
            "candidate_is_not_stable_memory": True,
        },
        "runs_dir": str(Path(runs_dir)),
    }
