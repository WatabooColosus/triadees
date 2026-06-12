"""Ciclo de nutrición neuronal verificable para Tríade Ω."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from triade.core.bodega_global_context import build_bodega_global_context
from triade.core.neuron_mission_selector import select_relevant_missions
from triade.core.neuron_missions import NeuronMissionStore
from triade.services.event_bus import publish_event
from triade.workers.contracts import WorkerRunConfig
from triade.workers.neuron_mission_executor import NeuronMissionExecutor


SAFE_NUTRITION_ACTIONS = {"observe", "diagnose", "propose_learning"}


def run_neuron_nutrition_cycle(
    db_path: str | Path = "triade/memory/triade.db",
    runs_dir: str | Path = "runs/background",
    mode: str = "observe_only",
    limit: int = 5,
) -> dict[str, Any]:
    """Ejecuta una pasada segura de nutrición neuronal.

    observe_only: solo observa y reporta.
    learn_candidates / execute_missions / full_local: selecciona misiones y
    ejecuta ciclos locales seguros por mission_id, sin consolidar memoria
    estable directamente.
    """
    db_path = Path(db_path)
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)

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

    store = NeuronMissionStore(db_path=db_path)
    active_missions = [
        mission
        for mission in store.list_missions(limit=200)
        if mission.status in {"candidate", "experimental", "stable"}
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
    selected_missions = selection.get("selected") or []

    if mode == "observe_only":
        return {
            "status": "ok",
            "mode": mode,
            "bodega_global": bodega_global,
            "missions_seen": len(active_missions),
            "missions_selected": len(selected_missions),
            "missions_executed": 0,
            "evidence_created": 0,
            "candidates_created": 0,
            "neurons_nourished": 0,
            "stable_memory_written": False,
            "identity_core_modified": False,
            "selection": selection,
            "summary": "observe_only: solo se revisa el estado vivo y la deuda operativa.",
        }

    executor = NeuronMissionExecutor(db_path=db_path)
    executed: list[dict[str, Any]] = []
    nourished_neuron_ids: set[int] = set()
    evidence_created = 0
    candidates_created = 0

    for item in selected_missions[:limit]:
        mission_id = int(item.get("id") or 0)
        mission = store.get_mission(mission_id)
        if mission is None:
            continue
        if not set(mission.allowed_actions or []).intersection(SAFE_NUTRITION_ACTIONS):
            continue
        result = executor.execute(
            mission_id=mission_id,
            run_ref=f"neuron-nutrition-{mission_id}",
            task_payload={
                "mode": mode,
                "query": "pulso vivo interno",
                "domain": mission.domain,
                "memory_context": bodega_global,
                "selected_by_nutrition": True,
                "selection_result": selection,
            },
            task_dir=runs_dir / f"nutrition-{mission_id}",
            config=WorkerRunConfig(task_timeout=30.0, runs_dir=str(runs_dir)),
        )
        executed.append(result)
        if result.get("evidence_id"):
            evidence_created += 1
        if result.get("learning_candidate"):
            candidates_created += 1
        if mission.neuron_id is not None:
            nourished_neuron_ids.add(int(mission.neuron_id))
        publish_event(
            "neuron_mission_selected",
            "neuron_nutrition",
            {"mission_id": mission_id, "title": mission.title, "relevance_score": item.get("relevance_score"), "mode": mode},
            db_path=db_path,
            run_ref=f"neuron-nutrition-{mission_id}",
        )
        publish_event(
            "neuron_mission_executed",
            "neuron_nutrition",
            {"mission_id": mission_id, "decision": result.get("decision"), "composite_score": result.get("composite_score")},
            db_path=db_path,
            run_ref=f"neuron-nutrition-{mission_id}",
        )
        publish_event(
            "neuron_evidence_created",
            "neuron_nutrition",
            {"mission_id": mission_id, "evidence_id": result.get("evidence_id")},
            db_path=db_path,
            run_ref=f"neuron-nutrition-{mission_id}",
        )
        if result.get("learning_candidate"):
            publish_event(
                "learning_candidate_created",
                "neuron_nutrition",
                {"mission_id": mission_id, "candidate_id": result["learning_candidate"].get("candidate_id")},
                db_path=db_path,
                run_ref=f"neuron-nutrition-{mission_id}",
            )

    summary = {
        "missions_seen": len(active_missions),
        "missions_selected": len(selected_missions),
        "missions_executed": len(executed),
        "evidence_created": evidence_created,
        "candidates_created": candidates_created,
        "neurons_nourished": len(nourished_neuron_ids),
        "stable_memory_written": False,
        "identity_core_modified": False,
    }

    return {
        "status": "ok",
        "mode": mode,
        "bodega_global": bodega_global,
        "missions_seen": len(active_missions),
        "missions_selected": len(selected_missions),
        "missions_executed": len(executed),
        "evidence_created": evidence_created,
        "candidates_created": candidates_created,
        "neurons_nourished": len(nourished_neuron_ids),
        "stable_memory_written": False,
        "identity_core_modified": False,
        "executed": executed,
        "selection": selection,
        "summary": summary,
    }
