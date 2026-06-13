"""Tríade Ω — Route handlers de API REST.

Todas las rutas /api/* excepto /api/ui/*.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import FileResponse, PlainTextResponse

from triade.core.life_pulse import LIFE_PULSE
from triade.core.context_engine import build_living_context_for_chat
from triade.core.internal_runtime import (
    build_internal_context_snapshot,
    build_runtime_heartbeat,
    get_internal_runtime_state,
    get_internal_runtime_supervisor,
    start_internal_runtime_background,
    stop_internal_runtime_background,
)
from triade.core.learning_journal import build_learning_journal
from triade.core.living_report import build_living_report
from triade.core.qualia import QUALIA
from triade.core.runner import TriadeRunner
from triade.core.repo_info import repo_info
from triade.core.neuron_candidate_governance import NeuronCandidateGovernance
from triade.core.neuron_dashboard import build_neuron_dashboard
from triade.core.neuron_identity_view import NeuronIdentityView
from triade.core.stable_neuron_audit import audit_stable_neurons, apply_stable_neuron_audit
from triade.core.neuron_activity_store import NeuronActivityStore
from triade.core.observability_view import TriadeObservabilityView
from triade.core.ollama_blood import check_ollama_blood
from triade.federation.contracts import (
    FederatedJobResultPayload,
    SignedEnvelope,
    ensure_sandbox_task,
    verify_envelope,
)
from triade.federation.federation import Federation
from triade.learning.pipeline import LearningPipeline
from triade.qualia.bus import QualiaBus
from triade.qualia.contracts import NeuronExperience
from triade.qualia.store import QualiaStore
from triade.federation.relay_client import PublicRelayClient, relay_capabilities_for_federation
from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_search import SemanticSearchEngine
from triade.models.compatibility_matrix import ModelCompatibilityMatrix
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_install_queue import ModelInstallQueue
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient, check_ollama_cognitive_health
from triade.workers.background_service import WorkerBackgroundService
from triade.workers.neuron_mission_backfill import backfill_neuron_missions, neuron_missions_doctor
from triade.core.neuron_nutrition import run_neuron_nutrition_cycle
from triade.services.event_bus import list_recent_events

from apps import services
from apps.gates.safety import safety_gate
from apps.services import (
    RunRequest,
    RouterRequest,
    LocalNodeRegisterRequest,
    LocalNodeHeartbeatRequest,
    LocalNodeJobResultRequest,
    DistributedRuntimeRequest,
    DistributedProbeRequest,
    DistributedModelDoctorRequest,
    AndroidLocalGenerateRequest,
    SemanticIngestRequest,
    SemanticEmbedRequest,
    SemanticSearchRequest,
    SemanticTransitionRequest,
    NeuronCandidateDecisionRequest,
    clean_model,
    system_payload,
    router_payload,
    relay_settings,
    load_local_node_tokens,
    save_local_node_tokens,
    local_node_capabilities,
    upsert_local_android_node,
    create_local_job,
    wait_local_job,
    local_federated_nodes,
    android_llm_host_nodes,
    split_text_for_nodes,
    merge_local_preprocess_results,
    build_model_capacity,
    build_system_pulse,
    model_install_queue,
    semantic_governance_doctor,
    federated_transport_doctor,
    operational_awareness_context,
    run_context_with_living_awareness,
)

router = APIRouter()

SIGNED_NONCE_TTL_SECONDS = 300
SIGNED_NONCE_CACHE: dict[str, float] = {}


def require_key(value: str | None) -> None:
    expected = os.getenv("TRIADE_API_KEY")
    if expected and value != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida o ausente."
        )


def _prune_signed_nonce_cache(now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    expired = [
        key
        for key, expires_at in SIGNED_NONCE_CACHE.items()
        if expires_at <= current
    ]
    for key in expired:
        SIGNED_NONCE_CACHE.pop(key, None)


def _remember_signed_nonce(node_id: str, nonce: str) -> None:
    now = time.monotonic()
    _prune_signed_nonce_cache(now)
    key = f"{node_id}:{nonce}"
    if key in SIGNED_NONCE_CACHE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nonce federado ya usado; posible replay bloqueado.",
        )
    SIGNED_NONCE_CACHE[key] = now + SIGNED_NONCE_TTL_SECONDS


def verify_signed_node_envelope(envelope: SignedEnvelope) -> None:
    tokens = load_local_node_tokens()
    secret = tokens.get(envelope.node_id)
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nodo no registrado para transporte firmado.",
        )
    if not verify_envelope(envelope, secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firma federada inválida o expirada.",
        )
    _remember_signed_nonce(envelope.node_id, envelope.nonce)
    if envelope.public_key:
        federation = Federation()
        node = federation.get_node(envelope.node_id)
        if node:
            federation.register_node(
                node_id=envelope.node_id,
                name=str(node.get("name") or envelope.node_id),
                owner=str(node.get("owner") or "single-port-local"),
                endpoint=node.get("endpoint"),
                public_key=envelope.public_key,
                trust_level=str(node.get("trust_level") or "medium"),
                permissions=node.get("permissions")
                or ["publish_capabilities", "request_compute"],
                capabilities=node.get("capabilities") or {},
            )



# ── Living Workers ─────────────────────────────────────────────────────

def _worker_service() -> WorkerBackgroundService:
    return WorkerBackgroundService()


@router.get("/workers/status")
def workers_status() -> dict[str, Any]:
    LIFE_PULSE.record_action("workers_status")
    return _worker_service().status()


@router.post("/workers/run-once")
def workers_run_once(dry_run: bool = False, task_timeout: float = 30.0) -> dict[str, Any]:
    LIFE_PULSE.record_action("workers_run_once")
    return _worker_service().run_once(dry_run=dry_run, task_timeout=task_timeout)


@router.post("/workers/start")
def workers_start(max_iterations: int = 5, sleep: float = 2.0, dry_run: bool = False, task_timeout: float = 30.0) -> dict[str, Any]:
    LIFE_PULSE.record_action("workers_start")
    return _worker_service().start(max_iterations=max_iterations, sleep_seconds=sleep, dry_run=dry_run, task_timeout=task_timeout)


@router.post("/workers/stop")
def workers_stop() -> dict[str, Any]:
    LIFE_PULSE.record_action("workers_stop")
    return _worker_service().stop()


@router.get("/workers/events")
def workers_events(limit: int = 50, run_ref: str | None = None) -> dict[str, Any]:
    LIFE_PULSE.record_action("workers_events")
    return _worker_service().events(limit=limit, run_ref=run_ref)


@router.get("/api/workers/events")
def api_workers_events(limit: int = 50, run_ref: str | None = None) -> dict[str, Any]:
    return workers_events(limit=limit, run_ref=run_ref)


@router.get("/workers/queue")
def workers_queue(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("workers_queue")
    return _worker_service().queue_status(status=status, limit=limit)


@router.get("/neurons/activity")
def neurons_activity(limit: int = 100, name: str | None = None) -> dict[str, Any]:
    LIFE_PULSE.record_action("neurons_activity")
    activity = NeuronActivityStore().list_activity(name=name, limit=limit)
    return {"status": "ok", "count": len(activity), "activity": activity}


@router.get("/learning/pending")
def learning_pending(limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("learning_pending")
    pipe = LearningPipeline()
    pending = []
    for state in ("candidate", "evaluated", "verified"):
        pending.extend(pipe.list_candidates(status=state, limit=limit))
    pending = pending[:limit]
    return {"status": "ok", "count": len(pending), "candidates": pending}



# ── QualiaBus ──────────────────────────────────────────────────────────

def _qualia_store() -> QualiaStore:
    return QualiaStore()


@router.get("/qualia/state")
def qualia_state(run_id: str | None = None, limit: int = 20) -> dict[str, Any]:
    LIFE_PULSE.record_action("qualia_state")
    store = _qualia_store()
    return {"status": "ok", "latest_state": store.latest_state(run_id=run_id), "states": store.list_states(run_id=run_id, limit=limit)}


@router.get("/qualia/experiences")
def qualia_experiences(run_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("qualia_experiences")
    rows = _qualia_store().list_experiences(run_id=run_id, limit=limit)
    return {"status": "ok", "count": len(rows), "experiences": rows}


@router.get("/qualia/signals")
def qualia_signals(run_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("qualia_signals")
    rows = _qualia_store().list_signals(run_id=run_id, limit=limit)
    return {"status": "ok", "count": len(rows), "signals": rows}


@router.get("/qualia/central-packets")
def qualia_central_packets(run_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("qualia_central_packets")
    rows = _qualia_store().list_central_packets(run_id=run_id, limit=limit)
    return {"status": "ok", "count": len(rows), "central_packets": rows}


@router.get("/qualia/storage-packets")
def qualia_storage_packets(run_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("qualia_storage_packets")
    rows = _qualia_store().list_storage_packets(run_id=run_id, limit=limit)
    return {"status": "ok", "count": len(rows), "storage_packets": rows}


@router.post("/qualia/publish-test")
def qualia_publish_test(body: dict[str, Any] | None = None) -> dict[str, Any]:
    LIFE_PULSE.record_action("qualia_publish_test")
    payload = body or {}
    exp = NeuronExperience(
        run_id=str(payload.get("run_id") or "qualia-api-test"),
        neuron_id=str(payload.get("neuron_id") or "qualia_api"),
        neuron_type=str(payload.get("neuron_type") or "api_test"),
        mission=str(payload.get("mission") or "Validar publicación segura de QualiaBus desde API."),
        source="api.qualia.publish_test",
        source_type="api_test",
        observation=str(payload.get("observation") or "Experiencia de prueba QualiaBus desde API."),
        extracted_pattern=str(payload.get("extracted_pattern") or "QualiaBus genera paquetes trazables."),
        proposed_learning=str(payload.get("proposed_learning") or ""),
        confidence=float(payload.get("confidence") or 0.7),
        risk=str(payload.get("risk") or "low"),
        usefulness=float(payload.get("usefulness") or 0.7),
        emotional_signal=payload.get("emotional_signal") if isinstance(payload.get("emotional_signal"), dict) else {"valence": 0.2},
        evidence_refs=payload.get("evidence_refs") if isinstance(payload.get("evidence_refs"), list) else ["api:/qualia/publish-test"],
    )
    return QualiaBus().publish_experience(exp, ingest_learning=bool(exp.proposed_learning))

# ── Health ──────────────────────────────────────────────────────────────

@router.get("/health")
@router.get("/api/health")
def health() -> dict[str, Any]:
    LIFE_PULSE.record_action("health")
    runner = TriadeRunner(use_ollama=False)
    hardware, ollama = system_payload()
    return {
        "status": "ok",
        "entity": "Tríade Ω",
        "mode": "single-port",
        "port": 8010,
        "security": {"api_key_required": bool(os.getenv("TRIADE_API_KEY"))},
        "repo": repo_info(),
        "hardware": hardware.to_dict(),
        "ollama": ollama,
        "doctor": runner.doctor(),
    }


# ── Router ──────────────────────────────────────────────────────────────

@router.get("/api/models/doctor")
def models_doctor_get(intent: str = "conversation", urgency: str = "medium") -> dict[str, Any]:
    LIFE_PULSE.record_action("router_doctor")
    return router_payload(intent=intent, urgency=urgency)


@router.post("/api/router/doctor")
def route_doctor(request: RouterRequest) -> dict[str, Any]:
    LIFE_PULSE.record_action("router_doctor")
    return router_payload(intent=request.intent, urgency=request.urgency)


# ── Modelos ─────────────────────────────────────────────────────────────

@router.get("/api/models/compatibility")
def model_compatibility() -> dict[str, Any]:
    LIFE_PULSE.record_action("model_compatibility")
    hardware, ollama = system_payload()
    matrix = ModelCompatibilityMatrix(
        hardware=hardware, available_models=ollama.get("models", [])
    )
    return {"status": "ok", "mode": "single-port", "ollama": ollama, "matrix": matrix.build()}


@router.get("/api/models/ollama/cognitive-health")
def ollama_cognitive_health() -> dict[str, Any]:
    LIFE_PULSE.record_action("ollama_cognitive_health")
    health = check_ollama_cognitive_health()
    return {"status": "ok", "cognitive_health": health, **health}


@router.get("/api/models/ollama/blood")
@router.get("/api/system/ollama-blood")
@router.get("/api/runtime/blood")
def ollama_blood_route() -> dict[str, Any]:
    LIFE_PULSE.record_action("ollama_blood")
    blood = check_ollama_blood()
    return {"status": blood.get("status"), "ollama_blood": blood, **blood}


@router.get("/api/models/install-queue")
def route_model_install_queue(include_allowed: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("model_install_queue")
    return model_install_queue(include_allowed=include_allowed)


# ── Sistema ─────────────────────────────────────────────────────────────

@router.get("/api/system/model-capacity")
def system_model_capacity(sync_relay: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("model_capacity")
    return build_model_capacity(sync_relay=sync_relay)


@router.get("/api/system/pulse")
def system_pulse_route(
    sync_relay: bool = True,
    intent: str = "conversation",
    urgency: str = "medium",
) -> dict[str, Any]:
    LIFE_PULSE.record_action("system_pulse")
    return build_system_pulse(sync_relay=sync_relay, intent=intent, urgency=urgency)


@router.get("/api/observability")
@router.get("/api/system/observability")
def observability(limit: int = 20) -> dict[str, Any]:
    LIFE_PULSE.record_action("observability")
    view = TriadeObservabilityView(
        system_pulse_fn=build_system_pulse,
        health_fn=health,
    )
    return view.build(limit=limit)


@router.get("/api/system/neurons")
def system_neurons(limit: int = 100) -> dict[str, Any]:
    LIFE_PULSE.record_action("system_neurons")
    dashboard = build_neuron_dashboard(limit=limit)
    identity = NeuronIdentityView().list(limit=limit)
    return {
        **dashboard,
        "mode": "neuron_identity_dashboard",
        "identity_view": identity,
        "neurons": identity.get("neurons", []),
        "dashboard_neurons": dashboard.get("neurons", []),
    }


@router.get("/api/system/neurons/full")
def system_neurons_full(limit: int = 100, mission_limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("system_neurons_full")
    import sqlite3
    from triade.core.neuron_missions import NeuronMissionStore

    dashboard = build_neuron_dashboard(limit=limit)
    identity = NeuronIdentityView().list(limit=limit)
    mission_store = NeuronMissionStore()
    missions = mission_store.list_missions(limit=mission_limit)
    missions_payload = []
    for mission in missions:
        mission_id = int(mission.id or 0)
        cycles = mission_store.list_cycles(mission_id, limit=5)
        evidence = mission_store.list_evidence(mission_id, limit=5)
        latest_score = mission_store.latest_score(mission_id)
        missions_payload.append({
            "mission": mission.to_dict(),
            "latest_cycles": [cycle.to_dict() for cycle in cycles],
            "latest_evidence": [item.to_dict() for item in evidence],
            "latest_score": latest_score.to_dict() if latest_score else None,
            "last_real_use": {
                "cycle_id": cycles[0].id if cycles else None,
                "evidence_id": evidence[0].id if evidence else None,
                "run_refs": [
                    ref for ref in ((cycles[0].evidence_refs if cycles else []) or [])
                    if str(ref).startswith("run:")
                ][:3],
            },
        })

    learning_usage = []
    try:
        with sqlite3.connect("triade/memory/triade.db") as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT candidate_id, source_ref, title, domain, status,
                run_use_count, avg_outcome_score, updated_at
                FROM learning_queue
                WHERE source_ref LIKE 'mission:%'
                ORDER BY updated_at DESC, id DESC
                LIMIT ?""",
                (mission_limit,),
            ).fetchall()
        learning_usage = [dict(row) for row in rows]
    except Exception:
        learning_usage = []

    return {
        "status": "ok",
        "mode": "full_neuron_operational_state",
        "summary": {
            "dashboard": dashboard.get("summary", {}),
            "identity": identity.get("summary", {}),
            "mission_count": len(missions_payload),
            "mission_learning_candidates": len(learning_usage),
        },
        "neurons": identity.get("neurons", []),
        "dashboard_neurons": dashboard.get("neurons", []),
        "missions": missions_payload,
        "learning_usage": learning_usage,
        "policy": {
            "read_only": True,
            "identity_core_protected": True,
            "candidate_is_not_stable_memory": True,
            "stable_requires_learning_pipeline": True,
        },
    }


@router.get("/api/system/neurons/{name}")
def system_neuron_detail(name: str, limit: int = 10) -> dict[str, Any]:
    from triade.core.neuron_registry import NeuronRegistry
    from triade.core.neuron_autopromoter import NeuronAutopromoter
    registry = NeuronRegistry()
    neuron = registry.get_neuron(name)
    if neuron is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Neurona no encontrada.")
    training = registry.list_training(neuron_id=int(neuron["id"]), limit=limit)
    ap = NeuronAutopromoter()
    progress = ap.compute_progress(dict(neuron), training)
    identity = NeuronIdentityView().detail(name, limit=limit)
    return {
        "status": "ok",
        "neuron": (identity or {}).get("neuron", dict(neuron)),
        "raw_neuron": dict(neuron),
        "training": training,
        "progress": progress,
        "identity_view": identity,
    }


@router.post("/api/system/neurons/{name}/promote")
def system_neuron_promote(name: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    from triade.core.neuron_registry import NeuronRegistry
    from triade.core.stable_promotion_readiness import evaluate_stable_readiness
    target = (body or {}).get("status", "experimental")
    valid = {"candidate_reviewable", "experimental", "stable", "rejected", "needs_changes"}
    if target not in valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Status inválido: {target}")
    if target == "stable":
        report = evaluate_stable_readiness(limit=200)
        item = next((n for n in report.get("neurons", []) if n.get("name") == name), None)
        if not item or not item.get("ready_for_stable_review"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "stable_requires_evidence",
                    "message": "Ninguna neurona puede declararse stable sin evidencia suficiente.",
                    "readiness": item or {},
                },
            )
    registry = NeuronRegistry()
    neuron = registry.update_status(name, target)
    return {"status": "ok", "neuron": NeuronIdentityView().detail(name, limit=20), "raw_neuron": neuron, "promoted_to": target}


# ── Neuron Missions ─────────────────────────────────────────────────────


@router.get("/api/neurons/missions")
def list_neuron_missions(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMissionStore
    store = NeuronMissionStore()
    missions = store.list_missions(status=status, limit=limit)
    return {
        "status": "ok",
        "count": len(missions),
        "missions": [m.to_dict() for m in missions],
    }


@router.get("/api/neurons/missions/relevant")
def relevant_missions(query: str = "", domain: str | None = None, limit: int = 5) -> dict[str, Any]:
    from triade.core.neuron_mission_selector import select_relevant_missions
    LIFE_PULSE.record_action("neuron_missions_relevant")
    return select_relevant_missions(
        user_input=query,
        domain=domain,
        limit=limit,
    )


@router.get("/api/system/neurons/missions/relevant")
def system_relevant_missions(query: str = "", domain: str | None = None, limit: int = 5) -> dict[str, Any]:
    from triade.core.neuron_mission_selector import select_relevant_missions
    LIFE_PULSE.record_action("system_neuron_missions_relevant")
    return select_relevant_missions(
        user_input=query,
        domain=domain,
        limit=limit,
    )


@router.post("/api/neuron_missions/backfill")
def backfill_neuron_missions_route(limit: int = 500) -> dict[str, Any]:
    LIFE_PULSE.record_action("neuron_missions_backfill")
    return backfill_neuron_missions(db_path="triade/memory/triade.db", runs_dir="runs", limit=limit)


@router.get("/api/neuron_missions/doctor")
def neuron_missions_doctor_route(limit: int = 500) -> dict[str, Any]:
    LIFE_PULSE.record_action("neuron_missions_doctor")
    return neuron_missions_doctor(db_path="triade/memory/triade.db", runs_dir="runs", limit=limit)


@router.post("/api/neurons/missions")
def create_neuron_mission(body: dict[str, Any]) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMission, NeuronMissionStore
    if not body.get("title") or not body.get("mission"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title y mission son requeridos")
    store = NeuronMissionStore()
    mission = NeuronMission(
        neuron_id=body.get("neuron_id"),
        title=str(body["title"]),
        mission=str(body["mission"]),
        domain=str(body.get("domain", "general")),
        allowed_sources=body.get("allowed_sources", ["worker", "run", "federation"]),
        allowed_actions=body.get("allowed_actions", ["observe", "diagnose", "propose_learning"]),
        schedule_hint=str(body.get("schedule_hint", "every_cycle")),
        status=str(body.get("status", "candidate")),
    )
    mission_id = store.create_mission(mission)
    created = store.get_mission(mission_id)
    return {"status": "ok", "mission": created.to_dict() if created else None, "mission_id": mission_id}


@router.get("/api/neurons/missions/{mission_or_neuron_id}")
def get_neuron_missions(mission_or_neuron_id: int) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMissionStore
    store = NeuronMissionStore()
    mission = store.get_mission(mission_or_neuron_id)
    if mission:
        score = store.latest_score(mission_or_neuron_id)
        return {
            "status": "ok",
            "lookup": "mission_id",
            "mission": mission.to_dict(),
            "latest_score": score.to_dict() if score else None,
        }
    missions = store.get_missions_by_neuron(mission_or_neuron_id)
    return {
        "status": "ok",
        "lookup": "neuron_id",
        "count": len(missions),
        "missions": [m.to_dict() for m in missions],
    }


@router.get("/api/neurons/missions/{mission_or_neuron_id}/cycles")
def get_neuron_mission_cycles(mission_or_neuron_id: int, limit: int = 20) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMissionStore
    store = NeuronMissionStore()
    mission = store.get_mission(mission_or_neuron_id)
    missions = [mission] if mission else store.get_missions_by_neuron(mission_or_neuron_id)
    all_cycles = []
    for m in missions:
        if m is None:
            continue
        cycles = store.list_cycles(m.id, limit=limit)
        all_cycles.extend([c.to_dict() for c in cycles])
    return {
        "status": "ok",
        "lookup": "mission_id" if mission else "neuron_id",
        "count": len(all_cycles),
        "cycles": all_cycles[:limit],
    }


@router.get("/api/neurons/missions/{mission_or_neuron_id}/evidence")
def get_neuron_mission_evidence(mission_or_neuron_id: int, limit: int = 20) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMissionStore
    store = NeuronMissionStore()
    mission = store.get_mission(mission_or_neuron_id)
    missions = [mission] if mission else store.get_missions_by_neuron(mission_or_neuron_id)
    all_evidence = []
    for m in missions:
        if m is None:
            continue
        evidence = store.list_evidence(m.id, limit=limit)
        all_evidence.extend([e.to_dict() for e in evidence])
    return {
        "status": "ok",
        "lookup": "mission_id" if mission else "neuron_id",
        "count": len(all_evidence),
        "evidence": all_evidence[:limit],
    }


@router.get("/api/neurons/missions/{mission_or_neuron_id}/scores")
def get_neuron_mission_scores_compat(mission_or_neuron_id: int, limit: int = 20) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMissionStore
    store = NeuronMissionStore()
    mission = store.get_mission(mission_or_neuron_id)
    mission_ids = [mission_or_neuron_id] if mission else [m.id for m in store.get_missions_by_neuron(mission_or_neuron_id) if m.id]
    scores = []
    with store._connect() as conn:
        for mission_id in mission_ids:
            rows = conn.execute(
                "SELECT * FROM neuron_scores WHERE mission_id = ? ORDER BY id DESC LIMIT ?",
                (mission_id, limit),
            ).fetchall()
            scores.extend([store._score_from_row(r).to_dict() for r in rows])
    return {
        "status": "ok",
        "lookup": "mission_id" if mission else "neuron_id",
        "count": len(scores[:limit]),
        "scores": scores[:limit],
    }


@router.get("/api/neurons/stable-audit")
def stable_neuron_audit(limit: int = 300) -> dict[str, Any]:
    LIFE_PULSE.record_action("stable_neuron_audit")
    return audit_stable_neurons(db_path="triade/memory/triade.db", runs_dir="runs", limit=limit)


@router.get("/api/system/neurons/stable-audit")
def system_stable_neuron_audit(limit: int = 300) -> dict[str, Any]:
    LIFE_PULSE.record_action("system_stable_neuron_audit")
    return audit_stable_neurons(db_path="triade/memory/triade.db", runs_dir="runs", limit=limit)


@router.post("/api/neurons/stable-audit/apply")
def stable_neuron_audit_apply(
    limit: int = 300,
    apply: bool = False,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    require_key(x_triade_api_key)
    LIFE_PULSE.record_action("stable_neuron_audit_apply")
    if not apply:
        read_only = audit_stable_neurons(
            db_path="triade/memory/triade.db",
            runs_dir="runs",
            limit=limit,
        )
        return {
            "status": "requires_explicit_apply",
            "message": "Debe enviar apply=true para aplicar cambios.",
            "read_only_result": read_only,
        }
    return apply_stable_neuron_audit(
        db_path="triade/memory/triade.db",
        runs_dir="runs",
        limit=limit,
        apply=True,
    )


@router.get("/api/neuron_missions/{mission_id}")
def get_neuron_mission_by_id(mission_id: int) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMissionStore
    store = NeuronMissionStore()
    mission = store.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Misión {mission_id} no encontrada")
    score = store.latest_score(mission_id)
    return {
        "status": "ok",
        "mission": mission.to_dict(),
        "latest_score": score.to_dict() if score else None,
    }


@router.get("/api/neuron_missions/{mission_id}/cycles")
def get_neuron_mission_cycles_by_id(mission_id: int, limit: int = 30) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMissionStore
    store = NeuronMissionStore()
    mission = store.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Misión {mission_id} no encontrada")
    cycles = store.list_cycles(mission_id, limit=limit)
    return {
        "status": "ok",
        "mission_id": mission_id,
        "count": len(cycles),
        "cycles": [c.to_dict() for c in cycles],
    }


@router.get("/api/neuron_missions/{mission_id}/evidence")
def get_neuron_mission_evidence_by_id(mission_id: int, limit: int = 30) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMissionStore
    store = NeuronMissionStore()
    mission = store.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Misión {mission_id} no encontrada")
    evidence = store.list_evidence(mission_id, limit=limit)
    return {
        "status": "ok",
        "mission_id": mission_id,
        "count": len(evidence),
        "evidence": [e.to_dict() for e in evidence],
    }


@router.get("/api/neuron_missions/{mission_id}/scores")
def get_neuron_mission_scores(mission_id: int, limit: int = 20) -> dict[str, Any]:
    from triade.core.neuron_missions import NeuronMissionStore
    store = NeuronMissionStore()
    mission = store.get_mission(mission_id)
    if not mission:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Misión {mission_id} no encontrada")
    with store._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM neuron_scores WHERE mission_id = ? ORDER BY id DESC LIMIT ?",
            (mission_id, limit),
        ).fetchall()
    scores = [store._score_from_row(r).to_dict() for r in rows]
    return {
        "status": "ok",
        "mission_id": mission_id,
        "count": len(scores),
        "scores": scores,
    }


@router.get("/api/internal/errors")
def list_internal_errors(
    scope: str | None = None,
    run_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    from triade.core.error_bus import ERROR_SEVERITY_POLICY, query_internal_errors
    errors = query_internal_errors(scope=scope, run_id=run_id, limit=limit)
    return {
        "status": "ok",
        "count": len(errors),
        "errors": errors,
        "severity_policy": ERROR_SEVERITY_POLICY,
    }


@router.get("/api/system/life")
def system_life(tick: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("life_snapshot")
    if tick:
        return LIFE_PULSE.tick()
    return LIFE_PULSE.snapshot()


@router.post("/api/system/life/continuous-runner")
def system_life_continuous_runner(body: dict[str, Any] | None = None) -> dict[str, Any]:
    LIFE_PULSE.record_action("life_continuous_runner_control")
    payload = body or {}
    enabled = bool(payload.get("enabled", False))
    result = LIFE_PULSE.configure_continuous_runner(
        enabled=enabled,
        autonomy_level=payload.get("autonomy_level"),
        interval_seconds=payload.get("interval_seconds"),
        max_cycles=payload.get("max_cycles"),
    )
    if result.get("status") != "ok":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result)
    return result


@router.get("/api/system/activity")
def system_activity() -> dict[str, Any]:
    LIFE_PULSE.record_action("system_activity")
    from triade.core.neuron_dashboard import build_neuron_dashboard
    dashboard = build_neuron_dashboard(limit=50)
    life = LIFE_PULSE.snapshot()
    neurons = dashboard.get("neurons", [])
    status_counts: dict[str, int] = {}
    for n in neurons:
        s = str(n.get("status") or "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
    promoted_recently = [
        {"name": n.get("name"), "status": n.get("status"), "progress": n.get("progress")}
        for n in neurons if n.get("progress", {}).get("progress", 0) >= 1.0
    ][-5:]
    return {
        "continuous_runner": life.get("continuous_runner", {}),
        "uptime_seconds": life.get("uptime_seconds"),
        "neurons_total": len(neurons),
        "neurons_by_status": status_counts,
        "promoted": promoted_recently,
        "latest_neurons": [
            {"name": n.get("name"), "status": n.get("status"), "progress": n.get("progress"), "domain": n.get("domain")}
            for n in neurons[:10]
        ],
    }


@router.get("/api/system/qualia")
def system_qualia(refresh_life: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("qualia_snapshot")
    return QUALIA.snapshot(refresh_life=refresh_life)


# ── Runtime interno 24/7 ───────────────────────────────────────────────


@router.get("/api/runtime/status")
def runtime_status() -> dict[str, Any]:
    LIFE_PULSE.record_action("runtime_status")
    return {
        "status": "ok",
        "supervisor": get_internal_runtime_state(),
        "context_snapshot": build_internal_context_snapshot(limit=10),
    }


@router.get("/api/runtime/heartbeat")
def runtime_heartbeat(since_hours: int = 24, limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("runtime_heartbeat")
    return build_runtime_heartbeat(since_hours=since_hours, limit=limit)


@router.post("/api/runtime/once")
def runtime_once(body: dict[str, Any] | None = None) -> dict[str, Any]:
    LIFE_PULSE.record_action("runtime_once")
    payload = body or {}
    result = get_internal_runtime_supervisor().run_once(mode=payload.get("mode"))
    event_ids = []
    for e in result.get("snapshot", {}).get("last_events", []):
        if e.get("event_type", "") in ("runtime_cycle_start", "runtime_cycle_complete",
                                        "runtime_cycle_started", "runtime_cycle_completed"):
            event_ids.append(e.get("id"))
    return {
        "status": result.get("status", "error"),
        "mode": result.get("mode", payload.get("mode", "observe_only")),
        "cycle_recorded": result.get("status") == "ok",
        "cycle_id": result.get("cycle_id"),
        "event_ids": event_ids,
        "started_at": next(iter(result.get("snapshot", {}).get("last_events", [])), {}).get("created_at") if result.get("status") == "ok" else None,
        "completed_at": (
            [e.get("created_at") for e in (result.get("snapshot", {}).get("last_events", []) or [])
             if e.get("event_type") in ("runtime_cycle_complete", "runtime_cycle_completed")] or [None]
        )[-1],
        "summary": {
            "services": list(result.get("services", {}).keys()) if result.get("status") == "ok" else [],
            "counters": result.get("counters", {}),
            "error": result.get("error"),
        },
    }


@router.post("/api/runtime/start")
def runtime_start(body: dict[str, Any] | None = None) -> dict[str, Any]:
    LIFE_PULSE.record_action("runtime_start")
    payload = body or {}
    from triade.core.internal_runtime import runtime_background_status
    result = start_internal_runtime_background(
        mode=payload.get("mode"),
        interval_seconds=payload.get("interval_seconds"),
        max_cycles=payload.get("max_cycles"),
    )
    bg = runtime_background_status()
    snapshot = result.get("snapshot", bg.get("snapshot", {}))
    return {
        "status": result.get("status", "error"),
        "mode": snapshot.get("mode", payload.get("mode", "observe_only")),
        "interval_seconds": payload.get("interval_seconds") or snapshot.get("interval_seconds", 30),
        "background_thread_alive": bg.get("background_thread_alive", False),
        "snapshot": snapshot,
    }


@router.post("/api/runtime/stop")
def runtime_stop() -> dict[str, Any]:
    LIFE_PULSE.record_action("runtime_stop")
    return stop_internal_runtime_background()


@router.get("/api/runtime/events")
def runtime_events(limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("runtime_events")
    events = list_recent_events(limit=limit)
    return {"status": "ok", "count": len(events), "events": events}


@router.get("/api/runtime/learning-journal")
def runtime_learning_journal(since_hours: int = 24, limit: int = 50) -> dict[str, Any]:
    LIFE_PULSE.record_action("runtime_learning_journal")
    return build_learning_journal(since_hours=since_hours, limit=limit)


@router.get("/api/runtime/neuron-nutrition")
def runtime_neuron_nutrition(mode: str = "observe_only", limit: int = 5) -> dict[str, Any]:
    LIFE_PULSE.record_action("runtime_neuron_nutrition")
    return run_neuron_nutrition_cycle(mode=mode, limit=limit)


@router.get("/api/runtime/context")
def runtime_context(user_input: str = "", limit: int = 10) -> dict[str, Any]:
    LIFE_PULSE.record_action("runtime_context")
    return build_living_context_for_chat(user_input=user_input, limit=limit)


@router.get("/api/system/living-context")
def system_living_context(user_input: str = "", limit: int = 10) -> dict[str, Any]:
    LIFE_PULSE.record_action("system_living_context")
    return build_living_context_for_chat(user_input=user_input, limit=limit)


@router.get("/api/system/living-report")
def system_living_report(limit: int = 20, summary: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("system_living_report")
    report = build_living_report(limit=limit)
    if summary:
        from triade.core.schemas import LivingReportResponse
        try:
            validated = LivingReportResponse(
                status=report.get("status", "ok"),
                runtime_enabled=report.get("runtime_enabled", False),
                runtime_mode=report.get("runtime_mode"),
                cycles_last_hour=report.get("cycles_last_hour", 0),
                missions_executed_last_hour=report.get("missions_executed_last_hour", 0),
                learning_candidates_created_last_hour=report.get("learning_candidates_created_last_hour", 0),
                workers_active=report.get("workers_active", False),
                runtime_continuity_score=report.get("runtime_continuity_score", 0.0),
                bodega_global_context_summary=report.get("bodega_global_context_summary", {}),
                stable_neuron_audit=report.get("stable_neuron_audit", {}),
            )
            return validated.model_dump()
        except Exception:
            return report
    return report


# ── Bodega Global Context ──────────────────────────────────────────────

@router.get("/api/bodega/global-context")
def bodega_global_context_get(query: str = "", limit: int = 10) -> dict[str, Any]:
    LIFE_PULSE.record_action("bodega_global_context")
    from triade.core.bodega_global_context import build_bodega_global_context
    return build_bodega_global_context(
        user_input=query or "contexto global",
        limit=limit,
        semantic_recall_enabled=True,
    )


@router.get("/api/system/bodega/global-context")
def system_bodega_global_context(query: str = "", limit: int = 10) -> dict[str, Any]:
    LIFE_PULSE.record_action("system_bodega_global_context")
    from triade.core.bodega_global_context import build_bodega_global_context
    return build_bodega_global_context(
        user_input=query or "contexto global",
        limit=limit,
        semantic_recall_enabled=True,
    )


# ── React Dashboard ─────────────────────────────────────────────────────


@router.get("/api/ui/react-dashboard")
def react_dashboard(query: str = "", limit: int = 5) -> dict[str, Any]:
    """Payload agregado vivo read-only para la SPA React.

    No ejecuta workers, no modifica memoria, no toca identity_core.
    """
    from triade.core.living_report import build_living_report
    from triade.core.bodega_global_context import build_bodega_global_context
    from triade.core.observability_view import TriadeObservabilityView
    from triade.core.ollama_blood import check_ollama_blood
    from triade.core.technical_debt_audit import build_technical_debt_audit
    from triade.core.repo_runtime_status import build_repo_runtime_status
    from triade.workers.background_service import WorkerBackgroundService
    from triade.services.event_bus import list_recent_events

    import time as _time
    import traceback as _traceback

    LIFE_PULSE.record_action("react_dashboard")

    _errors: list[dict[str, str]] = []

    def _safe(fn, block_name: str, default: Any = None):
        try:
            return fn()
        except Exception as exc:
            _errors.append({"block": block_name, "error": str(exc)[:200]})
            return default if default is not None else {"status": "unavailable", "error": str(exc)[:200]}

    heartbeat = _safe(lambda: build_living_report(summary=True), "heartbeat", {"status": "unavailable"})
    blood = _safe(lambda: check_ollama_blood(), "ollama_blood", {"status": "unavailable", "cognitive_blood_active": False})
    bodega_ctx = _safe(
        lambda: build_bodega_global_context(user_input=query or "dashboard", limit=limit, semantic_recall_enabled=True),
        "bodega_summary",
        {"memory_confidence": "unavailable"},
    )
    observability = _safe(lambda: TriadeObservabilityView().build(), "observability", {"status": "unavailable"})
    debt = _safe(lambda: build_technical_debt_audit(), "technical_debt", {"score": 0, "debts": [], "warnings": []})
    git = _safe(lambda: build_repo_runtime_status(), "git_status", {"status": "unavailable"})
    workers = _safe(lambda: WorkerBackgroundService().status(), "workers", {"status": "unavailable"})
    events = _safe(lambda: list_recent_events(limit=50), "runtime_events", [])

    return {
        "status": "partial" if _errors else "ok",
        "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%S"),
        "refresh_hint_seconds": 5,
        "errors": _errors,
        "heartbeat": {
            "api_server_alive": heartbeat.get("api_server_alive", True),
            "heartbeat_truth": heartbeat.get("heartbeat_truth", "API encendida, runtime apagado"),
            "runtime_enabled": heartbeat.get("runtime_enabled"),
            "mode": heartbeat.get("runtime_mode"),
            "cycles_last_hour": heartbeat.get("cycles_last_hour", 0),
            "cycles_last_24h": heartbeat.get("cycles_last_24h", 0),
            "runtime_continuity_score": heartbeat.get("runtime_continuity_score"),
            "latest_action": heartbeat.get("latest_action"),
            "latest_error": heartbeat.get("latest_error"),
            "missions_executed_last_hour": heartbeat.get("missions_executed_last_hour", 0),
            "workers_active": heartbeat.get("workers_active"),
            "background_thread_alive": heartbeat.get("background_thread_alive"),
        },
        "ollama_blood": {
            "status": blood.get("status"),
            "cognitive_blood_active": blood.get("cognitive_blood_active", False),
            "ollama_ok": blood.get("ollama_ok", False),
            "blood_pressure_score": blood.get("blood_pressure_score"),
            "base_url": blood.get("base_url"),
            "reasoning_model": blood.get("reasoning_model"),
            "embedding_model": blood.get("embedding_model"),
            "coder_model": blood.get("coder_model"),
            "can_reason": blood.get("can_reason", False),
            "can_embed": blood.get("can_embed", False),
            "can_nourish_neurons": blood.get("can_nourish_neurons", False),
            "can_evaluate_learning": blood.get("can_evaluate_learning", False),
            "can_consolidate_stable": blood.get("can_consolidate_stable", False),
            "degraded_components": blood.get("degraded_components", []),
            "recommended_action": blood.get("recommended_action"),
        },
        "observability": {
            "status": observability.get("status"),
            "memory_trace_summary": observability.get("last_run", {}).get("memory_trace_summary", {}),
        },
        "bodega_summary": {
            "memory_confidence": bodega_ctx.get("memory_confidence", "unknown"),
            "semantic_engine_status": bodega_ctx.get("semantic_engine_status", "unavailable"),
            "semantic_recall_mode": bodega_ctx.get("semantic_recall_mode", "unknown"),
            "semantic_learning_allowed": bodega_ctx.get("semantic_learning_allowed", False),
            "contradictions_count": len(bodega_ctx.get("contradictions") or []),
            "recommended_context_policy": bodega_ctx.get("recommended_context_policy"),
        },
        "learning_journal": {
            "cycles_last_24h": heartbeat.get("cycles_last_24h", 0),
            "missions_executed": heartbeat.get("missions_executed_last_hour", 0),
            "evidence_created": heartbeat.get("evidence_created_last_24h", 0),
            "candidates_created": heartbeat.get("learning_candidates_created_last_hour", 0),
            "candidates_evaluated": heartbeat.get("candidates_evaluated", 0),
            "candidates_verified": heartbeat.get("candidates_verified", 0),
            "candidates_consolidated": heartbeat.get("candidates_consolidated", 0),
            "candidates_rejected": heartbeat.get("candidates_rejected_last_24h", 0),
            "neurons_nourished": heartbeat.get("neurons_nourished", 0),
            "latest_learning_candidate": heartbeat.get("latest_learning_candidate"),
            "latest_rejection": heartbeat.get("latest_rejection"),
        },
        "technical_debt": {
            "score": debt.get("score", 0),
            "debts_count": debt.get("debts_count", 0),
            "warnings_count": debt.get("warnings_count", 0),
            "debts": debt.get("debts", []),
            "warnings": debt.get("warnings", []),
            "recommended_actions": debt.get("recommended_actions", []),
        },
        "git_status": {
            "status": git.get("status"),
            "branch": git.get("branch"),
            "commit": git.get("commit"),
            "dirty": git.get("dirty", False),
            "changed_files_count": git.get("changed_files_count", 0),
            "changed_files": git.get("changed_files", []),
            "recent_commits": git.get("recent_commits", []),
        },
        "system_processes": {
            "runtime_enabled": heartbeat.get("runtime_enabled"),
            "runtime_mode": heartbeat.get("mode"),
            "background_thread_alive": heartbeat.get("background_thread_alive", False),
            "workers_active": heartbeat.get("workers_active", False),
            "active_tasks": workers.get("active_tasks", 0),
            "cycles_last_hour": heartbeat.get("cycles_last_hour", 0),
            "cycles_last_24h": heartbeat.get("cycles_last_24h", 0),
            "latest_action": heartbeat.get("latest_action"),
            "latest_error": heartbeat.get("latest_error"),
        },
        "workers": {
            "status": workers.get("status"),
            "active_tasks": workers.get("active_tasks", 0),
            "last_run_ref": workers.get("last_run_ref"),
            "summary": workers.get("summary"),
        },
        "runtime_events": events[:20] if isinstance(events, list) else [],
        "policy": {
            "read_only": True,
            "identity_core_protected": True,
            "no_shell_execution": True,
        },
    }


# ── Technical Debt ────────────────────────────────────────────────────


@router.get("/api/system/technical-debt")
def system_technical_debt() -> dict[str, Any]:
    from triade.core.technical_debt_audit import build_technical_debt_audit
    LIFE_PULSE.record_action("technical_debt")
    return build_technical_debt_audit()


@router.get("/api/ui/technical-debt")
def ui_technical_debt_alias() -> dict[str, Any]:
    from triade.core.technical_debt_audit import build_technical_debt_audit
    LIFE_PULSE.record_action("technical_debt")
    return build_technical_debt_audit()


# ── Federación ──────────────────────────────────────────────────────────

@router.get("/api/federation/resource-lease")
def federation_resource_lease_endpoint(sync_relay: bool = True) -> dict[str, Any]:
    capacity = build_model_capacity(sync_relay=sync_relay)
    lease = capacity["federation"]["resource_lease"]
    lease["local"] = {
        "hardware": capacity["local"]["hardware"],
        "ollama": capacity["local"]["ollama"],
        "docker": capacity["local"]["docker"],
    }
    return lease


@router.get("/api/federation/transport/doctor")
def route_federated_transport_doctor() -> dict[str, Any]:
    return federated_transport_doctor()


@router.post("/api/federation/transport/next")
def federated_transport_next(envelope: SignedEnvelope) -> dict[str, Any]:
    verify_signed_node_envelope(envelope)
    for job in services.LOCAL_JOBS.values():
        if job.get("node_id") == envelope.node_id and job.get("status") == "pending":
            ensure_sandbox_task(str(job.get("task") or ""))
            job["status"] = "running"
            job["updated_at"] = time.time()
            return {"status": "ok", "node_id": envelope.node_id, "job": job}
    return {"status": "idle", "node_id": envelope.node_id, "job": None}


@router.post("/api/federation/transport/result")
def federated_transport_result(envelope: SignedEnvelope) -> dict[str, Any]:
    verify_signed_node_envelope(envelope)
    payload = FederatedJobResultPayload(**envelope.payload)
    return local_node_job_result_impl(
        payload.job_id,
        LocalNodeJobResultRequest(
            node_id=envelope.node_id,
            node_token=load_local_node_tokens().get(envelope.node_id, ""),
            status=payload.status,
            result=payload.result,
            error=payload.error,
        ),
    )


# ── Nodos locales ──────────────────────────────────────────────────────

@router.post("/api/register")
def local_node_register(request: LocalNodeRegisterRequest) -> dict[str, Any]:
    node_id = "local-" + secrets.token_hex(5)
    node_token = secrets.token_urlsafe(24)
    tokens = load_local_node_tokens()
    tokens[node_id] = node_token
    save_local_node_tokens(tokens)
    node = upsert_local_android_node(node_id, request.display_name, request.capabilities)
    return {
        "status": "ok",
        "node_id": node_id,
        "node_token": node_token,
        "node": node,
        "capabilities": node["capabilities"],
    }


@router.post("/api/heartbeat")
def local_node_heartbeat(request: LocalNodeHeartbeatRequest) -> dict[str, Any]:
    tokens = load_local_node_tokens()
    known = tokens.get(request.node_id)
    if known and request.node_token != known:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de nodo inválido."
        )
    if not known:
        tokens[request.node_id] = request.node_token or secrets.token_urlsafe(24)
        save_local_node_tokens(tokens)
    node = upsert_local_android_node(request.node_id, request.node_id, request.capabilities)
    return {"status": "ok", "node": node}


@router.get("/api/jobs/next")
def local_node_next_job(node_id: str, node_token: str = "") -> dict[str, Any]:
    tokens = load_local_node_tokens()
    if tokens.get(node_id) and tokens[node_id] != node_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de nodo inválido."
        )
    for job in services.LOCAL_JOBS.values():
        if job.get("node_id") == node_id and job.get("status") == "pending":
            job["status"] = "running"
            job["updated_at"] = time.time()
            return {"status": "ok", "node_id": node_id, "job": job}
    return {"status": "idle", "node_id": node_id, "job": None}


@router.post("/api/jobs/{job_id}/result")
def local_node_job_result(job_id: str, request: LocalNodeJobResultRequest) -> dict[str, Any]:
    return local_node_job_result_impl(job_id, request)


def local_node_job_result_impl(job_id: str, request: LocalNodeJobResultRequest) -> dict[str, Any]:
    tokens = load_local_node_tokens()
    if tokens.get(request.node_id) and tokens[request.node_id] != request.node_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de nodo inválido."
        )
    job = services.LOCAL_JOBS.setdefault(job_id, {"job_id": job_id, "node_id": request.node_id})
    job["status"] = request.status
    job["result"] = request.result
    job["error"] = request.error
    job["updated_at"] = time.time()
    if request.status == "completed" and isinstance(request.result, dict):
        federation = Federation()
        node = federation.get_node(request.node_id)
        if node:
            capabilities = dict(node.get("capabilities") or {})
            task = str(job.get("task") or request.result.get("task") or "")
            if task == "browser_benchmark":
                capabilities["last_benchmark"] = request.result
                capabilities["benchmark_score"] = int(
                    request.result.get("score")
                    or capabilities.get("benchmark_score")
                    or 0
                )
            elif task == "preprocess_text":
                capabilities["last_preprocess"] = {
                    "job_id": job_id,
                    "chars": request.result.get("chars"),
                    "word_count": request.result.get("word_count"),
                    "approx_tokens": request.result.get("approx_tokens"),
                    "updated_at": job["updated_at"],
                }
            elif task == "federated_inference_probe":
                capabilities["last_inference_probe"] = {
                    "job_id": job_id,
                    "status": request.result.get("status", "completed"),
                    "ops": request.result.get("ops"),
                    "prompt_sha256": request.result.get("prompt_sha256"),
                    "updated_at": job["updated_at"],
                }
            elif task == "android_model_doctor":
                capabilities["last_android_model_doctor"] = {
                    **request.result,
                    "job_id": job_id,
                    "updated_at": job["updated_at"],
                }
                capabilities["edge_model_runtime"] = True
                capabilities["model_runtime_backend"] = (
                    request.result.get("backend")
                    or capabilities.get("model_runtime_backend")
                    or "none"
                )
                capabilities["can_run_local_llm"] = bool(
                    request.result.get("can_run_local_llm")
                )
                capabilities["local_model_runtime_ready"] = bool(
                    request.result.get("native_backend_present")
                    and request.result.get("can_run_local_llm")
                )
                capabilities["available_local_models"] = (
                    request.result.get("available_models")
                    or capabilities.get("available_local_models")
                    or []
                )
                capabilities["supported_model_formats"] = (
                    request.result.get("supported_model_formats")
                    or capabilities.get("supported_model_formats")
                    or []
                )
                capabilities = local_node_capabilities(request.node_id, capabilities)
            elif task == "android_local_generate":
                capabilities["last_android_local_generate"] = {
                    "job_id": job_id,
                    "status": request.result.get("status"),
                    "ok": request.result.get("ok"),
                    "backend": request.result.get("backend"),
                    "model": request.result.get("model"),
                    "threads": request.result.get("threads"),
                    "elapsed_ms": request.result.get("elapsed_ms"),
                    "prompt_sha256": request.result.get("prompt_sha256"),
                    "updated_at": job["updated_at"],
                }
                if request.result.get("ok"):
                    capabilities["can_run_local_llm"] = True
                    capabilities["local_model_runtime_ready"] = True
                    capabilities["model_runtime_backend"] = (
                        request.result.get("backend")
                        or capabilities.get("model_runtime_backend")
                    )
                    capabilities = local_node_capabilities(request.node_id, capabilities)
            capabilities["compute_status"] = "ready"
            capabilities["distributed_runtime_status"] = "active"
            federation.update_capabilities(request.node_id, capabilities)
    return {"status": "ok", "job_id": job_id, "accepted": True}


# ── Federación local ────────────────────────────────────────────────────

@router.post("/api/local-federation/benchmark")
def local_federation_benchmark(
    seconds: float = 1.0, wait_timeout: float = 25.0
) -> dict[str, Any]:
    nodes = local_federated_nodes("browser_benchmark")
    if not nodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay dispositivos federados locales online.",
        )
    node = nodes[0]
    job = create_local_job(
        str(node["node_id"]), task="browser_benchmark", seconds=seconds
    )
    result = wait_local_job(str(job["job_id"]), timeout=wait_timeout)
    return {
        "status": "ok" if result.get("status") == "completed" else result.get("status"),
        "node_id": node["node_id"],
        "job": result,
    }


# ── Runtime distribuido ────────────────────────────────────────────────

@router.get("/api/distributed-runtime/status")
def distributed_runtime_status() -> dict[str, Any]:
    capacity = build_model_capacity(sync_relay=False)
    authorized = capacity["federation"]["authorized"]
    active = bool(authorized["active_job_runtime"])
    return {
        "status": "ok",
        "mode": "distributed-runtime",
        "runtime": authorized["runtime"],
        "active_job_runtime": active,
        "nodes": local_federated_nodes(),
        "supported_tasks": authorized["supported_runtime_tasks"],
        "truth": "Activo para jobs de CPU/preproceso; pendiente runtime tensor-paralelo para una sola inferencia LLM distribuida."
        if active
        else "Pendiente: conecta la app Android directamente al 8010/LAN para que tome jobs locales. La inferencia LLM tensor-paralela sigue pendiente.",
    }


@router.post("/api/distributed-runtime/preprocess")
def distributed_runtime_preprocess(
    request: DistributedRuntimeRequest,
) -> dict[str, Any]:
    nodes = local_federated_nodes("preprocess_text")
    if not nodes:
        relay = relay_settings()
        if relay.get("admin_token"):
            federation = Federation()
            result = PublicRelayClient(
                str(relay["url"]), str(relay["admin_token"]), timeout=12
            ).preprocess_text_online(
                federation,
                text=request.text,
                max_chunk_chars=request.max_chunk_chars,
                wait_timeout=request.wait_timeout,
            )
            if result.get("completed"):
                return {
                    "status": "ok",
                    "mode": "distributed-runtime",
                    "task": "preprocess_text",
                    "transport": "public_relay_fallback",
                    "submitted": result.get("submitted", 0),
                    "completed": result.get("completed", 0),
                    "nodes_used": [
                        item.get("node_id") for item in result.get("results", [])
                    ],
                    "jobs": result.get("results", []),
                    "model_feed": result.get("model_feed", {}),
                    "truth": "Preproceso ejecutado por relay publico porque no hay nodos LAN directos al 8010.",
                }
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay nodos Android locales con preprocess_text online ni respuesta util via relay publico.",
        )
    shards = split_text_for_nodes(request.text, len(nodes))
    jobs = []
    for index, shard in enumerate(shards):
        node = nodes[index % len(nodes)]
        job = create_local_job(
            str(node["node_id"]),
            task="preprocess_text",
            payload={
                "text": shard,
                "max_chunk_chars": request.max_chunk_chars,
                "shard_index": index,
                "shard_count": len(shards),
                "signal": "feed_local_model_context",
            },
            seconds=1.0,
        )
        jobs.append(job)
    results = [
        wait_local_job(str(job["job_id"]), timeout=request.wait_timeout) for job in jobs
    ]
    completed = [job for job in results if job.get("status") == "completed"]
    return {
        "status": "ok" if completed else "degraded",
        "mode": "distributed-runtime",
        "task": "preprocess_text",
        "submitted": len(jobs),
        "completed": len(completed),
        "nodes_used": sorted({str(job.get("node_id")) for job in jobs}),
        "jobs": results,
        "model_feed": merge_local_preprocess_results(completed),
    }


@router.post("/api/distributed-runtime/probe")
def distributed_runtime_probe(request: DistributedProbeRequest) -> dict[str, Any]:
    nodes = local_federated_nodes("federated_inference_probe")
    if not nodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay nodos Android locales con federated_inference_probe online.",
        )
    jobs = []
    for node in nodes:
        jobs.append(
            create_local_job(
                str(node["node_id"]),
                task="federated_inference_probe",
                payload={
                    "prompt": request.prompt,
                    "iterations": request.iterations,
                    "signal": "probe_distributed_inference_runtime",
                },
                seconds=1.0,
            )
        )
    results = [
        wait_local_job(str(job["job_id"]), timeout=request.wait_timeout) for job in jobs
    ]
    completed = [job for job in results if job.get("status") == "completed"]
    return {
        "status": "ok" if completed else "degraded",
        "mode": "distributed-runtime",
        "task": "federated_inference_probe",
        "submitted": len(jobs),
        "completed": len(completed),
        "total_ops": sum(
            int((job.get("result") or {}).get("ops") or 0) for job in completed
        ),
        "jobs": results,
        "truth": "Probe ejecutado en Android. Aun no es inferencia LLM tensor-paralela ni memoria unificada de Ollama.",
    }


@router.post("/api/distributed-runtime/android-model-doctor")
def distributed_runtime_android_model_doctor(
    request: DistributedModelDoctorRequest,
) -> dict[str, Any]:
    nodes = local_federated_nodes("android_model_doctor")
    jobs = []
    transport = "lan_8010"
    if nodes:
        for node in nodes:
            jobs.append(
                create_local_job(
                    str(node["node_id"]), task="android_model_doctor", seconds=1.0
                )
            )
        results = [
            wait_local_job(str(job["job_id"]), timeout=request.wait_timeout)
            for job in jobs
        ]
    else:
        relay = relay_settings()
        results = []
        transport = "public_relay_fallback"
        if relay.get("admin_token"):
            federation = Federation()
            client = PublicRelayClient(
                str(relay["url"]), str(relay["admin_token"]), timeout=12
            )
            sync = client.sync_nodes_to_federation(federation)
            for node in sync.get("nodes", []):
                capabilities = node.get("capabilities") or {}
                if not capabilities.get("online") or "android_model_doctor" not in capabilities.get(
                    "allowed_tasks", []
                ):
                    continue
                job_id = client.create_job(
                    str(node["node_id"]), task="android_model_doctor", seconds=1.0
                )
                results.append(
                    {
                        "job_id": job_id,
                        "node_id": node["node_id"],
                        "job": client.wait_for_job(job_id, timeout=request.wait_timeout),
                    }
                )
    completed = [
        item
        for item in results
        if (
            item.get("status") == "completed"
            or (item.get("job") or {}).get("status") == "completed"
        )
    ]
    doctors = [
        (item.get("result") or (item.get("job") or {}).get("result") or {})
        for item in completed
    ]
    ready_hosts = [doctor for doctor in doctors if doctor.get("can_run_local_llm")]
    return {
        "status": "ok" if completed else "degraded",
        "mode": "distributed-runtime",
        "task": "android_model_doctor",
        "transport": transport,
        "submitted": len(jobs) if transport == "lan_8010" else len(results),
        "completed": len(completed),
        "can_host_llm_count": len(ready_hosts),
        "doctors": doctors,
        "jobs": results,
        "truth": "Android puede hospedar modelos solo cuando can_run_local_llm=true y exista backend nativo cargado.",
    }


@router.post("/api/distributed-runtime/android-local-generate")
def distributed_runtime_android_local_generate(
    request: AndroidLocalGenerateRequest,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": request.prompt,
        "model": request.model or "",
        "max_tokens": request.max_tokens,
        "context_tokens": request.context_tokens,
        "timeout_seconds": int(request.wait_timeout),
        "signal": "android_native_llm_generation",
    }
    if request.threads:
        payload["threads"] = request.threads

    local_nodes = android_llm_host_nodes(
        local_federated_nodes("android_local_generate")
    )
    if request.node_id:
        local_nodes = [
            node
            for node in local_nodes
            if str(node.get("node_id")) == request.node_id
        ]
    if local_nodes:
        node = local_nodes[0]
        job = create_local_job(
            str(node["node_id"]),
            task="android_local_generate",
            payload=payload,
            seconds=1.0,
        )
        result = wait_local_job(str(job["job_id"]), timeout=request.wait_timeout)
        completed = result.get("status") == "completed" and bool(
            (result.get("result") or {}).get("ok")
        )
        return {
            "status": "ok" if completed else result.get("status", "degraded"),
            "mode": "distributed-runtime",
            "task": "android_local_generate",
            "transport": "lan_8010",
            "node_id": node["node_id"],
            "job": result,
            "response": (result.get("result") or {}).get("response"),
            "truth": "Generacion ejecutada por backend LLM nativo en Android."
            if completed
            else "El nodo Android acepto el job pero no completo generacion LLM real.",
        }

    relay = relay_settings()
    if relay.get("admin_token"):
        federation = Federation()
        client = PublicRelayClient(
            str(relay["url"]), str(relay["admin_token"]), timeout=12
        )
        sync = client.sync_nodes_to_federation(federation)
        relay_hosts = android_llm_host_nodes(sync.get("nodes", []))
        if request.node_id:
            relay_hosts = [
                node
                for node in relay_hosts
                if str(node.get("node_id")) == request.node_id
            ]
        if relay_hosts:
            node = relay_hosts[0]
            job_id = client.create_job(
                str(node["node_id"]),
                task="android_local_generate",
                payload=payload,
                seconds=1.0,
            )
            job = client.wait_for_job(job_id, timeout=request.wait_timeout)
            completed = job.get("status") == "completed" and bool(
                (job.get("result") or {}).get("ok")
            )
            return {
                "status": "ok" if completed else job.get("status", "degraded"),
                "mode": "distributed-runtime",
                "task": "android_local_generate",
                "transport": "public_relay_fallback",
                "node_id": node["node_id"],
                "job": job,
                "response": (job.get("result") or {}).get("response"),
                "truth": "Generacion ejecutada por backend LLM nativo en Android via relay publico."
                if completed
                else "El relay encontro host Android, pero la generacion no completo correctamente.",
            }

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No hay host LLM Android real. Ejecuta Doctor Android y prepara la APK con llama-cli ejecutable en bin/ y un modelo .gguf en models/.",
    )


# ── Safety ───────────────────────────────────────────────────────────────

@router.get("/api/safety/pending")
def safety_pending() -> dict[str, Any]:
    """Lista runs pendientes de aprobación humana."""
    from apps.gates.safety import get_pending_approvals
    pending = get_pending_approvals()
    items = []
    for run_id, result in pending.items():
        safety = result.get("safety", {})
        items.append({
            "run_id": run_id,
            "status": safety.get("status"),
            "risk_level": safety.get("risk_level"),
            "reason": safety.get("reason"),
            "controls": safety.get("required_controls"),
            "response": result.get("response", "")[:200],
            "timestamp": safety.get("timestamp"),
        })
    return {"status": "ok", "count": len(items), "pending": items}


@router.post("/api/safety/approve/{run_id}")
def safety_approve(run_id: str) -> dict[str, Any]:
    """Aprueba un run pendiente y retorna el resultado completo."""
    from apps.gates.safety import remove_pending_approval
    result = remove_pending_approval(run_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No hay run pendiente con run_id '{run_id}'.",
        )
    result["safety"]["status"] = "approved"
    return result


@router.post("/api/safety/reject/{run_id}")
def safety_reject(run_id: str) -> dict[str, Any]:
    """Rechaza un run pendiente y lo descarta."""
    from apps.gates.safety import remove_pending_approval
    result = remove_pending_approval(run_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No hay run pendiente con run_id '{run_id}'.",
        )
    return {"status": "ok", "run_id": run_id, "disposition": "rejected"}


# ── Memoria semántica ──────────────────────────────────────────────────

@router.get("/api/semantic/doctor")
def semantic_doctor() -> dict[str, Any]:
    LIFE_PULSE.record_action("semantic_doctor")
    return SemanticEmbeddingEngine().doctor()


@router.get("/api/semantic/governance/doctor")
def route_semantic_governance_doctor() -> dict[str, Any]:
    LIFE_PULSE.record_action("semantic_governance_doctor")
    return semantic_governance_doctor()


@router.post("/api/semantic/ingest-and-embed")
def semantic_ingest_and_embed(
    request: SemanticIngestRequest,
    x_triade_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return SemanticEmbeddingEngine().ingest_and_embed(
        content=request.content,
        domain=request.domain,
        source_type=request.source_type,
        source_ref=request.source_ref,
        metadata=request.metadata,
        model=clean_model(request.model),
    )


@router.post("/api/semantic/documents/{document_id}/embed")
def semantic_embed_document(
    document_id: str,
    request: SemanticEmbedRequest,
    x_triade_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return SemanticEmbeddingEngine().embed_document(
        document_id, model=clean_model(request.model)
    ).to_dict()


@router.post("/api/semantic/documents/{document_id}/transition")
def semantic_transition_document(
    document_id: str,
    request: SemanticTransitionRequest,
    x_triade_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_key(x_triade_api_key)
    try:
        return SemanticMemoryGovernance().transition_document(
            document_id=document_id,
            new_status=request.new_status,
            reason=request.reason,
            approved_by=request.approved_by,
            evidence=request.evidence,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.post("/api/semantic/search")
def semantic_search_route(
    request: SemanticSearchRequest,
    x_triade_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return SemanticSearchEngine().search(
        query=request.query,
        model=clean_model(request.model),
        limit=request.limit,
        min_similarity=request.min_similarity,
        domain=request.domain,
    )


# ── Neuronas ────────────────────────────────────────────────────────────

@router.get("/api/neurons/candidates")
def list_neuron_candidates(
    limit_runs: int = 50,
    include_decided: bool = True,
    x_triade_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return NeuronCandidateGovernance().list_candidates(
        limit_runs=limit_runs, include_decided=include_decided
    )


@router.post("/api/neurons/candidates/approve")
def approve_neuron_candidate(
    request: NeuronCandidateDecisionRequest,
    x_triade_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return NeuronCandidateGovernance().approve(
        run_id=request.run_id,
        name=request.name,
        approved_by=request.decided_by,
        notes=request.notes,
    )


@router.post("/api/neurons/candidates/reject")
def reject_neuron_candidate(
    request: NeuronCandidateDecisionRequest,
    x_triade_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return NeuronCandidateGovernance().reject(
        run_id=request.run_id,
        name=request.name,
        rejected_by=request.decided_by,
        notes=request.notes,
    )


# ── Run ─────────────────────────────────────────────────────────────────

@router.post("/api/run")
@router.post("/triade/run")
def run_triade(
    request: RunRequest,
    x_triade_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    LIFE_PULSE.record_action("run")
    require_key(x_triade_api_key)
    try:
        ctx = run_context_with_living_awareness(request.context)
        if request.conversation_history:
            ctx["conversation_history"] = request.conversation_history[-20:]
        runner = TriadeRunner(
            use_ollama=request.use_ollama,
            hypothalamus_model=clean_model(request.hypothalamus_model),
            central_model=clean_model(request.central_model),
            auto_select_models=request.auto_select_models,
        )
        result = runner.run(
            request.text,
            source=request.source,
            context=ctx,
            semantic_recall_enabled=request.semantic_recall_enabled,
            semantic_model=clean_model(request.semantic_model),
            semantic_limit=request.semantic_limit,
            semantic_min_similarity=request.semantic_min_similarity,
            semantic_domain=request.semantic_domain,
            semantic_allow_experimental=request.semantic_allow_experimental,
        )
        return safety_gate(result)
    except HTTPException:
        raise
    except Exception as exc:
        LIFE_PULSE.record_action("run_error")
        return {
            "status": "error",
            "mode": "run_error",
            "response": f"Error interno ejecutando Tríade: {exc}",
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "system_events": [
                {
                    "type": "run_error",
                    "severity": "error",
                    "status": "failed",
                    "message": str(exc),
                    "action_required": "inspect_uvicorn_logs_and_runner",
                }
            ],
            "truth": "El endpoint /api/run devolvió JSON de error para proteger la UI; revisar logs de uvicorn para traceback completo.",
        }


# ── Downloads ───────────────────────────────────────────────────────────

@router.get("/downloads/triade-android-node.apk")
def download_android_node_apk() -> FileResponse:
    if not services.ANDROID_APK_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="APK Android no encontrado."
        )
    return FileResponse(
        services.ANDROID_APK_PATH,
        media_type="application/vnd.android.package-archive",
        filename="triade-android-node.apk",
    )


@router.get("/downloads/android/runtime-manifest")
def android_runtime_manifest() -> dict[str, Any]:
    llama_ready = services.ANDROID_LLAMA_CLI_PATH.exists()
    model_ready = services.ANDROID_BASE_MODEL_PATH.exists()
    return {
        "status": "ok" if llama_ready and model_ready else "incomplete",
        "mode": "android-runtime-bootstrap",
        "llama_cli": {
            "ready": llama_ready,
            "url": "/downloads/android/llama-cli",
            "expected_path": str(services.ANDROID_LLAMA_CLI_PATH),
            "install_target": "APK private bin/llama-cli",
        },
        "base_model": {
            "ready": model_ready,
            "url": "/downloads/android/base-model.gguf",
            "expected_path": str(services.ANDROID_BASE_MODEL_PATH),
            "install_target": "APK private models/triade-base.gguf",
        },
        "termux_bootstrap": {
            "url": "/downloads/android/termux-bootstrap.sh",
            "note": "La APK no puede ejecutar comandos dentro de Termux; el usuario debe abrir Termux y ejecutar el script si quiere preparar ese entorno.",
        },
        "truth": "8010 sirve los artefactos si existen localmente. No descarga modelos con licencia por su cuenta ni instala paquetes en Termux desde otra app.",
    }


@router.get("/downloads/android/llama-cli")
def download_android_llama_cli() -> FileResponse:
    if not services.ANDROID_LLAMA_CLI_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"llama-cli Android no encontrado. Coloca el binario arm64 en {services.ANDROID_LLAMA_CLI_PATH}.",
        )
    return FileResponse(
        services.ANDROID_LLAMA_CLI_PATH,
        media_type="application/octet-stream",
        filename="llama-cli",
    )


@router.get("/downloads/android/base-model.gguf")
def download_android_base_model() -> FileResponse:
    if not services.ANDROID_BASE_MODEL_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Modelo base GGUF no encontrado. Coloca un modelo pequeno en {services.ANDROID_BASE_MODEL_PATH}.",
        )
    return FileResponse(
        services.ANDROID_BASE_MODEL_PATH,
        media_type="application/octet-stream",
        filename="triade-base.gguf",
    )


@router.get("/downloads/android/termux-bootstrap.sh", response_class=PlainTextResponse)
def download_android_termux_bootstrap() -> str:
    return """#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

echo "[triade] Preparando Termux para nodo Android..."
pkg update -y
pkg install -y git curl wget proot clang cmake make python
python -m ensurepip --upgrade || true
python -m pip install --upgrade pip wheel || true

mkdir -p "$HOME/triade-runtime/bin" "$HOME/triade-runtime/models"
echo "[triade] Directorios listos:"
echo "  $HOME/triade-runtime/bin"
echo "  $HOME/triade-runtime/models"
echo
echo "[triade] Descarga o compila llama.cpp para Android/Termux y copia llama-cli a:"
echo "  $HOME/triade-runtime/bin/llama-cli"
echo "[triade] Copia un modelo GGUF pequeno a:"
echo "  $HOME/triade-runtime/models/triade-base.gguf"
echo
echo "[triade] Nota: la APK no puede instalar paquetes dentro de Termux desde otra app."
echo "[triade] Este script prepara Termux cuando lo ejecutas manualmente dentro de Termux."
"""
