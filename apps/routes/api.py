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
from triade.core.qualia import QUALIA
from triade.core.runner import TriadeRunner
from triade.core.repo_info import repo_info
from triade.core.neuron_candidate_governance import NeuronCandidateGovernance
from triade.core.neuron_dashboard import build_neuron_dashboard
from triade.federation.contracts import (
    FederatedJobResultPayload,
    SignedEnvelope,
    ensure_sandbox_task,
    verify_envelope,
)
from triade.federation.federation import Federation
from triade.federation.relay_client import PublicRelayClient, relay_capabilities_for_federation
from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_search import SemanticSearchEngine
from triade.models.compatibility_matrix import ModelCompatibilityMatrix
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_install_queue import ModelInstallQueue
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient

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


def require_key(value: str | None) -> None:
    expected = os.getenv("TRIADE_API_KEY")
    if expected and value != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida o ausente."
        )


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


@router.get("/api/system/neurons")
def system_neurons(limit: int = 100) -> dict[str, Any]:
    LIFE_PULSE.record_action("system_neurons")
    return build_neuron_dashboard(limit=limit)


@router.get("/api/system/neurons/{name}")
def system_neuron_detail(name: str, limit: int = 10) -> dict[str, Any]:
    from triade.core.neuron_registry import NeuronRegistry
    registry = NeuronRegistry()
    neuron = registry.get_neuron(name)
    if neuron is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Neurona no encontrada.")
    training = registry.list_training(neuron_id=int(neuron["id"]), limit=limit)
    return {"status": "ok", "neuron": dict(neuron), "training": training}


@router.get("/api/system/life")
def system_life(tick: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("life_snapshot")
    if tick:
        return LIFE_PULSE.tick()
    return LIFE_PULSE.snapshot()


@router.get("/api/system/qualia")
def system_qualia(refresh_life: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("qualia_snapshot")
    return QUALIA.snapshot(refresh_life=refresh_life)


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
