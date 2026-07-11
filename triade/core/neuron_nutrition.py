"""Ciclo de nutrición neuronal verificable para Tríade Ω."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.bodega_global_context import build_bodega_global_context
from triade.core.neuron_mission_selector import select_relevant_missions
from triade.core.neuron_missions import NeuronMissionStore
from triade.core.ollama_blood import check_ollama_blood, ollama_blood_policy
from triade.models.ollama_client import check_ollama_cognitive_health
from triade.services.event_bus import publish_event
from triade.workers.contracts import WorkerRunConfig
from triade.workers.neuron_mission_executor import NeuronMissionExecutor


SAFE_NUTRITION_ACTIONS = {"observe", "diagnose", "propose_learning"}
ACTIVE_MISSION_STATUSES = {"experimental", "stable"}


def run_neuron_nutrition_cycle(
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
    mode: str = "observe_only",
    limit: int = 5,
) -> dict[str, Any]:
    """Ejecuta una pasada segura de nutrición neuronal.

    Sin Ollama solo se ejecutan misiones activas cuyo alcance sea completamente
    local y seguro. Si no existe una misión elegible, el ciclo se degrada a
    ``observe_only`` para conservar el contrato histórico.
    """
    db_path = Path(db_path)
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    ollama_blood = check_ollama_blood()
    blood_policy = ollama_blood_policy("neuron_nutrition", ollama_blood)
    ollama_health = check_ollama_cognitive_health()
    model_policy = blood_policy
    degraded_mode = bool(blood_policy.get("degraded") or not blood_policy.get("allowed"))
    learning_allowed = bool(blood_policy.get("allowed"))
    stable_write_allowed = False
    model_used = {
        "model_provider": "ollama" if blood_policy.get("model_used") else "fallback",
        "model_name": blood_policy.get("model_used"),
        "model_required": False,
        "model_status": ollama_blood.get("status"),
        "ollama_blood_active": bool(ollama_blood.get("cognitive_blood_active")),
    }

    bodega_global = build_bodega_global_context(
        user_input="pulso vivo interno",
        db_path=db_path,
        runs_dir=runs_dir,
        limit=limit,
        semantic_recall_enabled=True,
    )
    publish_event(
        "bodega_global_reviewed",
        "neuron_nutrition",
        {"mode": mode, "status": bodega_global.get("status"), "memory_confidence": bodega_global.get("memory_confidence")},
        db_path=db_path,
        run_ref="neuron-nutrition",
    )
    publish_event(
        "ollama_blood_checked",
        "neuron_nutrition",
        {"status": ollama_blood.get("status"), "blood_pressure_score": ollama_blood.get("blood_pressure_score")},
        db_path=db_path,
        run_ref="neuron-nutrition",
    )

    store = NeuronMissionStore(db_path=db_path)
    active_missions = [
        mission
        for mission in store.list_missions(limit=200)
        if mission.status in ACTIVE_MISSION_STATUSES
    ]
    query_seed = " ".join(
        filter(
            None,
            [
                "pulso vivo interno",
                *(str(mission.title or "") for mission in active_missions[:5]),
                *(str(mission.domain or "") for mission in active_missions[:5]),
                *(str(mission.mission or "") for mission in active_missions[:3]),
            ],
        )
    ).strip()
    domain_seed = str(active_missions[0].domain) if active_missions else None
    selection = select_relevant_missions(
        user_input=query_seed or "pulso vivo interno",
        domain=domain_seed,
        memory_context={
            "project_context": {
                "domain": domain_seed or str((bodega_global.get("bodega_global_context_summary") or {}).get("recommended_context_policy") or ""),
                "topics": [str(mission.domain or "") for mission in active_missions[:10]],
            },
            "domain": domain_seed,
        },
        db_path=db_path,
        limit=limit,
    )
    selected_missions = [
        item
        for item in (selection.get("selected") or [])
        if int(item.get("id") or 0) in {int(m.id or 0) for m in active_missions}
    ]
    safe_selected = []
    for item in selected_missions:
        mission = store.get_mission(int(item.get("id") or 0))
        if mission and set(mission.allowed_actions or []).intersection(SAFE_NUTRITION_ACTIONS):
            safe_selected.append(item)

    effective_mode = mode
    if degraded_mode and mode != "observe_only" and not safe_selected:
        effective_mode = "observe_only"

    if not blood_policy.get("allowed"):
        publish_event(
            "neuron_nutrition_degraded_no_blood",
            "neuron_nutrition",
            {
                "requested_mode": mode,
                "effective_mode": effective_mode,
                "degraded_reason": blood_policy.get("reason"),
                "blocked_actions": model_policy.get("blocked_actions", []),
                "local_safe_execution": bool(safe_selected and effective_mode != "observe_only"),
            },
            severity="warning",
            db_path=db_path,
            run_ref="neuron-nutrition",
        )

    if effective_mode == "observe_only":
        return {
            "status": "ok",
            "mode": "observe_only",
            "requested_mode": mode,
            "ollama_blood": ollama_blood,
            "ollama_health": ollama_health,
            "model_policy": model_policy,
            "cognitive_blood_active": bool(ollama_blood.get("cognitive_blood_active")),
            "degraded_mode": degraded_mode,
            "can_nourish_neurons": bool(safe_selected),
            "model_used": model_used,
            "learning_allowed": learning_allowed,
            "stable_write_allowed": stable_write_allowed,
            "bodega_global": bodega_global,
            "missions_seen": len(active_missions),
            "missions_selected": len(safe_selected),
            "missions_executed": 0,
            "evidence_created": 0,
            "candidates_created": 0,
            "neurons_nourished": 0,
            "stable_memory_written": False,
            "identity_core_modified": False,
            "selection": selection,
            "summary": "observe_only: solo se revisa el estado vivo y la deuda operativa.",
            "reason": blood_policy.get("reason") if degraded_mode else None,
        }

    executor = NeuronMissionExecutor(db_path=db_path)
    executed: list[dict[str, Any]] = []
    nourished_entities: set[str] = set()
    evidence_created = 0
    candidates_created = 0

    for item in safe_selected[:limit]:
        mission_id = int(item.get("id") or 0)
        mission = store.get_mission(mission_id)
        if mission is None:
            continue
        task_payload = {
            "mode": effective_mode,
            "query": "pulso vivo interno",
            "domain": mission.domain,
            "memory_context": bodega_global,
            "selected_by_nutrition": True,
            "selection_result": selection,
            "model_policy": model_policy,
            "evidence": model_used,
            "model_used": model_used,
            "cognitive_blood_active": bool(ollama_blood.get("cognitive_blood_active")),
            "degraded_local_safe": degraded_mode,
        }
        # El executor interpreta la presencia explícita de ollama_blood como una
        # exigencia de modelo. En ejecución local degradada se omite para usar su
        # ruta determinista y mantener bloqueada toda escritura estable.
        if not degraded_mode:
            task_payload["ollama_blood"] = ollama_blood

        result = executor.execute(
            mission_id=mission_id,
            run_ref=f"neuron-nutrition-{mission_id}",
            task_payload=task_payload,
            task_dir=runs_dir / f"nutrition-{mission_id}",
            config=WorkerRunConfig(task_timeout=30.0, runs_dir=str(runs_dir)),
        )
        executed.append(result)
        if result.get("evidence_id"):
            evidence_created += 1
        if result.get("learning_candidate"):
            candidates_created += 1
            result["learning_candidate"]["model_provider"] = model_used["model_provider"]
            result["learning_candidate"]["model_name"] = model_used["model_name"]
            result["learning_candidate"]["model_required"] = False
        if result.get("status") == "completed":
            nourished_entities.add(
                f"neuron:{mission.neuron_id}" if mission.neuron_id is not None else f"mission:{mission_id}"
            )
        publish_event(
            "neuron_mission_executed",
            "neuron_nutrition",
            {"mission_id": mission_id, "decision": result.get("decision"), "composite_score": result.get("composite_score")},
            db_path=db_path,
            run_ref=f"neuron-nutrition-{mission_id}",
        )

    completed = [item for item in executed if item.get("status") == "completed"]
    summary = {
        "missions_seen": len(active_missions),
        "missions_selected": len(safe_selected),
        "missions_executed": len(completed),
        "evidence_created": evidence_created,
        "candidates_created": candidates_created,
        "neurons_nourished": len(nourished_entities),
        "stable_memory_written": False,
        "identity_core_modified": False,
    }
    return {
        "status": "ok",
        "mode": effective_mode,
        "requested_mode": mode,
        "ollama_blood": ollama_blood,
        "ollama_health": ollama_health,
        "model_policy": model_policy,
        "cognitive_blood_active": bool(ollama_blood.get("cognitive_blood_active")),
        "degraded_mode": degraded_mode,
        "can_nourish_neurons": bool(safe_selected),
        "model_used": model_used,
        "learning_allowed": learning_allowed,
        "stable_write_allowed": stable_write_allowed,
        "bodega_global": bodega_global,
        **summary,
        "executed": executed,
        "selection": selection,
        "summary": summary,
    }
