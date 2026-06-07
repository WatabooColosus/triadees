"""Tríade Ω Single Port App.

Puerto único 8010 para UI, health, router, compatibilidad, memoria semántica y runs locales.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from triade.core.life_pulse import LIFE_PULSE
from triade.core.qualia import QUALIA
from triade.core.runner import TriadeRunner
from triade.core.repo_info import repo_info
from triade.core.experimental_neuron_evidence import build_experimental_evidence_ledger
from triade.core.stable_promotion_readiness import evaluate_stable_readiness
from triade.core.system_pulse_builder import build_system_pulse as build_system_pulse_core
from triade.core.pulse_context import build_run_context_with_pulse
from triade.core.neuron_candidate_governance import NeuronCandidateGovernance
from triade.core.neuron_dashboard import build_neuron_dashboard
from triade.core.ui_manifest import build_ui_manifest
from triade.federation.contracts import (
    FederatedJobResultPayload,
    FederatedTransportDoctor,
    SignedEnvelope,
    ensure_sandbox_task,
    verify_envelope,
)
from triade.federation.federation import Federation
from triade.federation.node_live_registry import NODE_LIVE_REGISTRY
from triade.federation.relay_client import PublicRelayClient, relay_capabilities_for_federation
from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_search import SemanticSearchEngine
from triade.models.compatibility_matrix import ModelCompatibilityMatrix
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_install_queue import ModelInstallQueue
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient
from triade.federation.edge_router import EdgeRouter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    LIFE_PULSE.start()
    NODE_LIVE_REGISTRY.start()
    try:
        yield
    finally:
        NODE_LIVE_REGISTRY.stop()
        LIFE_PULSE.stop()


app = FastAPI(title="Tríade Ω Single Port", version="0.9.0", lifespan=lifespan)
ANDROID_APK_PATH = Path(os.environ.get("TRIADE_ANDROID_APK", "apps/static/triade-android-node.apk"))
ANDROID_RUNTIME_DIR = Path(os.environ.get("TRIADE_ANDROID_RUNTIME_DIR", "apps/static/android-runtime"))
ANDROID_LLAMA_CLI_PATH = Path(os.environ.get("TRIADE_ANDROID_LLAMA_CLI", str(ANDROID_RUNTIME_DIR / "llama-cli")))
ANDROID_BASE_MODEL_PATH = Path(os.environ.get("TRIADE_ANDROID_BASE_MODEL", str(ANDROID_RUNTIME_DIR / "triade-base.gguf")))
LOCAL_JOBS: dict[str, dict[str, Any]] = {}

class RunRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source: str = "single-port-ui"
    use_ollama: bool = False
    hypothalamus_model: str | None = None
    central_model: str | None = None
    auto_select_models: bool = True
    context: dict[str, Any] = Field(default_factory=dict)
    semantic_recall_enabled: bool = False
    semantic_model: str | None = None
    semantic_limit: int = Field(default=3, ge=1, le=20)
    semantic_min_similarity: float = Field(default=0.55, ge=-1.0, le=1.0)
    semantic_domain: str | None = None
    semantic_allow_experimental: bool = False


class RouterRequest(BaseModel):
    intent: str = "conversation"
    urgency: str = "medium"


class LocalNodeRegisterRequest(BaseModel):
    pairing_token: str = ""
    display_name: str = "Android Node"
    capabilities: dict[str, Any] = Field(default_factory=dict)


class LocalNodeHeartbeatRequest(BaseModel):
    node_id: str
    node_token: str = ""
    capabilities: dict[str, Any] = Field(default_factory=dict)


class LocalNodeJobResultRequest(BaseModel):
    node_id: str
    node_token: str = ""
    status: str = "completed"
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class DistributedRuntimeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    max_chunk_chars: int = Field(default=1200, ge=200, le=8000)
    wait_timeout: float = Field(default=30.0, ge=1.0, le=120.0)


class DistributedProbeRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    iterations: int = Field(default=250000, ge=1000, le=2000000)
    wait_timeout: float = Field(default=30.0, ge=1.0, le=120.0)


class DistributedModelDoctorRequest(BaseModel):
    wait_timeout: float = Field(default=30.0, ge=1.0, le=120.0)


class AndroidLocalGenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str | None = None
    node_id: str | None = None
    max_tokens: int = Field(default=128, ge=1, le=1024)
    context_tokens: int = Field(default=2048, ge=256, le=8192)
    threads: int | None = Field(default=None, ge=1, le=64)
    wait_timeout: float = Field(default=90.0, ge=5.0, le=600.0)


class SemanticIngestRequest(BaseModel):
    content: str = Field(..., min_length=1)
    domain: str = "general"
    source_type: str = "manual"
    source_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    model: str | None = None


class SemanticEmbedRequest(BaseModel):
    model: str | None = None


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    model: str | None = None
    limit: int = Field(default=5, ge=1, le=50)
    min_similarity: float = Field(default=-1.0, ge=-1.0, le=1.0)
    domain: str | None = None


class SemanticTransitionRequest(BaseModel):
    new_status: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    approved_by: str = "human"
    evidence: dict[str, Any] = Field(default_factory=dict)


class NeuronCandidateDecisionRequest(BaseModel):
    run_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    decided_by: str = "human"
    notes: str = ""


def clean_model(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def require_key(value: str | None) -> None:
    expected = os.getenv("TRIADE_API_KEY")
    if expected and value != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida o ausente.")


def system_payload() -> tuple[object, dict[str, Any]]:
    hardware = HardwareProfiler().detect()
    ollama = OllamaClient().health()
    return hardware, ollama


def router_payload(intent: str = "conversation", urgency: str = "medium") -> dict[str, Any]:
    hardware, ollama = system_payload()
    router = ModelRouter(available_models=ollama.get("models", []), hardware=hardware)
    return {"status": "ok", "mode": "single-port", "hardware": hardware.to_dict(), "ollama": ollama, "router": router.route_many(intent=intent, urgency=urgency)}


def relay_settings() -> dict[str, str | None]:
    url = os.getenv("TRIADE_RELAY_URL", "https://web-production-8cffa0.up.railway.app")
    token = os.getenv("TRIADE_RELAY_ADMIN_TOKEN")
    token_path = os.getenv("TRIADE_RELAY_TOKEN_FILE", ".triade-relay.tokens.local")
    if not token and os.path.exists(token_path):
        for line in open(token_path, encoding="utf-8", errors="ignore"):
            if line.startswith("TRIADE_RELAY_ADMIN_TOKEN="):
                token = line.split("=", 1)[1].strip()
                break
    return {"url": url, "admin_token": token}


def local_node_token_path() -> Path:
    return Path("triade/memory/local_node_tokens.json")


def load_local_node_tokens() -> dict[str, str]:
    path = local_node_token_path()
    if not path.exists():
        return {}
    try:
        import json

        return dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def save_local_node_tokens(tokens: dict[str, str]) -> None:
    import json

    path = local_node_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8")


def local_node_capabilities(node_id: str, capabilities: dict[str, Any]) -> dict[str, Any]:
    return relay_capabilities_for_federation(
        {"node_id": node_id, "online": True, "capabilities": capabilities},
        "http://127.0.0.1:8010",
    )


def upsert_local_android_node(node_id: str, name: str, capabilities: dict[str, Any]) -> dict[str, Any]:
    return Federation().register_node(
        node_id=node_id,
        name=name,
        owner="single-port-local",
        endpoint="http://127.0.0.1:8010",
        trust_level="medium",
        permissions=["publish_capabilities", "request_compute"],
        capabilities=local_node_capabilities(node_id, capabilities),
    )


def create_local_job(node_id: str, task: str, payload: dict[str, Any] | None = None, seconds: float = 1.0) -> dict[str, Any]:
    task = ensure_sandbox_task(task)
    job_id = "localjob-" + secrets.token_hex(6)
    job = {
        "job_id": job_id,
        "node_id": node_id,
        "task": task,
        "payload": payload or {},
        "seconds": seconds,
        "status": "pending",
        "created_at": time.time(),
        "updated_at": time.time(),
        "result": {},
        "error": None,
    }
    LOCAL_JOBS[job_id] = job
    return job


def verify_signed_node_envelope(envelope: SignedEnvelope) -> None:
    tokens = load_local_node_tokens()
    secret = tokens.get(envelope.node_id)
    if not secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nodo no registrado para transporte firmado.")
    if not verify_envelope(envelope, secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Firma federada inválida o expirada.")
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
                permissions=node.get("permissions") or ["publish_capabilities", "request_compute"],
                capabilities=node.get("capabilities") or {},
            )


def wait_local_job(job_id: str, timeout: float = 25.0, interval: float = 0.5) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = LOCAL_JOBS.get(job_id) or {}
        if job.get("status") in {"completed", "failed"}:
            return job
        time.sleep(interval)
    job = LOCAL_JOBS.get(job_id) or {"job_id": job_id}
    job["status"] = "timeout"
    job["error"] = "Tiempo de espera agotado esperando al nodo local."
    return job


def local_federated_nodes(task: str | None = None) -> list[dict[str, Any]]:
    nodes = []
    for node in Federation().list_nodes(status="active"):
        caps = node.get("capabilities") or {}
        allowed = caps.get("allowed_tasks") if isinstance(caps.get("allowed_tasks"), list) else []
        relay_url = str(caps.get("relay_url") or node.get("endpoint") or "")
        is_direct_local = "127.0.0.1:8010" in relay_url or "localhost:8010" in relay_url or "192.168." in relay_url
        if not (caps.get("federation_complete") and caps.get("online")):
            continue
        if not is_direct_local:
            continue
        if task and task not in allowed:
            continue
        nodes.append(node)
    return nodes


def android_llm_host_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hosts = []
    for node in nodes:
        caps = node.get("capabilities") or {}
        support = caps.get("model_support") or {}
        allowed = caps.get("allowed_tasks") if isinstance(caps.get("allowed_tasks"), list) else []
        if "android_local_generate" not in allowed:
            continue
        if bool(support.get("can_host_llm") or caps.get("can_run_local_llm") or caps.get("local_model_runtime_ready")):
            hosts.append(node)
    return hosts


def split_text_for_nodes(text: str, count: int) -> list[str]:
    clean = " ".join(str(text).split())
    if count <= 1 or len(clean) <= 1:
        return [clean]
    target = max(1, len(clean) // count)
    shards: list[str] = []
    start = 0
    for index in range(count):
        if index == count - 1:
            shards.append(clean[start:].strip())
            break
        end = min(len(clean), start + target)
        boundary = clean.rfind(" ", start, min(len(clean), end + 200))
        if boundary <= start:
            boundary = end
        shards.append(clean[start:boundary].strip())
        start = min(len(clean), boundary + 1)
    return [shard for shard in shards if shard]


def merge_local_preprocess_results(completed_jobs: list[dict[str, Any]]) -> dict[str, Any]:
    keyword_counts: dict[str, int] = {}
    chunks: list[dict[str, Any]] = []
    total_words = 0
    total_chars = 0
    for job in completed_jobs:
        result = job.get("result") or {}
        total_words += int(result.get("word_count") or 0)
        total_chars += int(result.get("chars") or 0)
        for keyword in result.get("keywords") or []:
            term = str(keyword.get("term") or "").strip().lower()
            if term:
                keyword_counts[term] = keyword_counts.get(term, 0) + int(keyword.get("count") or 0)
        for chunk in result.get("chunks") or []:
            if isinstance(chunk, dict):
                chunks.append({**chunk, "node_id": job.get("node_id"), "source_job_id": job.get("job_id")})
    keywords = [
        {"term": term, "count": count}
        for term, count in sorted(keyword_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:24]
    ]
    return {
        "ready_for_local_model": bool(completed_jobs),
        "chars": total_chars,
        "word_count": total_words,
        "approx_tokens": int(total_words * 1.35) if total_words else 0,
        "keywords": keywords,
        "chunks": chunks,
        "note": "Contexto procesado por nodos Android nativos y devuelto al 8010 para alimentar el modelo local.",
    }


def tool_status(name: str, command: list[str]) -> dict[str, Any]:
    path = shutil.which(command[0])
    if not path:
        return {"installed": False, "path": None, "ok": False, "version": "not_found"}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        text = (result.stdout or result.stderr or "").strip().splitlines()
        return {"installed": True, "path": path, "ok": result.returncode == 0, "version": text[0] if text else "unknown"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"installed": True, "path": path, "ok": False, "version": "error", "error": str(exc)}


def docker_status() -> dict[str, Any]:
    docker_path = shutil.which("docker")
    candidates = [
        Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"),
        Path(r"C:\Program Files\Docker\Docker\DockerCli.exe"),
    ]
    if not docker_path:
        docker_path = next((str(candidate) for candidate in candidates if candidate.exists()), None)
    if not docker_path:
        return {"installed": False, "path": None, "ok": False, "version": "not_found", "engine": "not_found"}
    try:
        version = subprocess.run([docker_path, "--version"], capture_output=True, text=True, timeout=5, check=False)
        info = subprocess.run([docker_path, "info", "--format", "{{json .ServerVersion}}"], capture_output=True, text=True, timeout=8, check=False)
        version_text = (version.stdout or version.stderr or "").strip().splitlines()
        error_text = (info.stderr or "").strip()
        return {
            "installed": True,
            "path": docker_path,
            "ok": info.returncode == 0,
            "version": version_text[0] if version_text else "unknown",
            "engine": "running" if info.returncode == 0 else "stopped",
            "server_version": (info.stdout or "").strip().strip('"') if info.returncode == 0 else None,
            "error": error_text or None,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"installed": True, "path": docker_path, "ok": False, "version": "error", "engine": "error", "error": str(exc)}


def node_model_readiness(node: dict[str, Any]) -> dict[str, Any]:
    caps = node.get("capabilities") or {}
    support = caps.get("model_support") or {}
    ram = float(caps.get("ram_available_gb") or caps.get("device_memory_gb") or 0.0)
    authorized_ram = float(caps.get("ram_authorized_gb") or support.get("authorized_ram_gb") or 0.0)
    cpu = int(caps.get("cpu_count") or 1)
    authorized_cpu = int(caps.get("cpu_authorized_count") or support.get("authorized_cpu_count") or 0)
    native_android = bool(caps.get("native_android"))
    can_host_llm = bool(support.get("can_host_llm"))
    federation_complete = bool(caps.get("federation_complete") or (native_android and caps.get("online") and authorized_cpu > 0))
    feed_ready = bool(support.get("ready_for_model_management")) and federation_complete
    missing: list[str] = []
    if not caps.get("online"):
        missing.append("heartbeat online reciente")
    if native_android and not can_host_llm:
        missing.append("runtime nativo de modelos en Android (Ollama/llama.cpp/ONNX)")
    effective_ram = authorized_ram if native_android else ram
    effective_cpu = authorized_cpu if native_android else 0
    if effective_ram < 4:
        missing.append("RAM libre >= 4 GB para modelos 3B tranquilos")
    if effective_ram < 8:
        missing.append("RAM libre >= 8 GB para 7B/8B")
    if not caps.get("gpus"):
        missing.append("GPU/VRAM reportada para aceleracion")
    runnable = []
    feed_only = []
    for model, required in ModelRouter.MODEL_RAM_GB.items():
        if can_host_llm and effective_ram >= required:
            runnable.append(model)
        elif feed_ready and effective_cpu >= 1:
            feed_only.append(model)
    return {
        "node_id": node.get("node_id"),
        "name": node.get("name") or node.get("display_name"),
        "online": caps.get("online"),
        "native_android": native_android,
        "cpu_count": cpu,
        "cpu_authorized_count": authorized_cpu,
        "ram_available_gb": ram,
        "ram_authorized_gb": authorized_ram,
        "resource_limit_percent": int(caps.get("resource_limit_percent") or support.get("resource_limit_percent") or 0),
        "resource_limit_reported": bool(caps.get("resource_limit_reported") or support.get("resource_limit_reported")),
        "resource_limit_source": caps.get("resource_limit_source") or support.get("resource_limit_source") or "unknown",
        "federation_complete": federation_complete,
        "benchmark_score": caps.get("benchmark_score", 0),
        "recommended_use": support.get("recommended_use", "unknown"),
        "can_host_llm": can_host_llm,
        "can_feed_local_models": feed_ready,
        "edge_model_runtime": bool(caps.get("edge_model_runtime") or support.get("edge_model_runtime")),
        "model_runtime_backend": caps.get("model_runtime_backend") or support.get("model_runtime_backend") or "none",
        "local_model_runtime_ready": bool(caps.get("local_model_runtime_ready") or support.get("local_model_runtime_ready")),
        "runnable_models": runnable,
        "feed_targets": feed_only,
        "missing_for_comfortable_models": missing,
        "capabilities": caps,
    }


def federated_model_plan(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    feeders = [node for node in nodes if node["can_feed_local_models"] and node["federation_complete"]]
    runtime_ready = [
        node for node in feeders
        if "preprocess_text" in ((node.get("capabilities") or {}).get("allowed_tasks") or [])
        and (
            "127.0.0.1:8010" in str((node.get("capabilities") or {}).get("relay_url") or "")
            or "localhost:8010" in str((node.get("capabilities") or {}).get("relay_url") or "")
            or "192.168." in str((node.get("capabilities") or {}).get("relay_url") or "")
        )
    ]
    total_cpu = sum(int(node.get("cpu_authorized_count") or 0) for node in feeders)
    total_ram = round(sum(float(node.get("ram_authorized_gb") or 0.0) for node in feeders), 2)
    total_available_ram = round(sum(float(node.get("ram_available_gb") or 0.0) for node in feeders), 2)
    total_vram = 0.0
    gpu_nodes = 0
    for node in feeders:
        caps = node.get("capabilities") or {}
        gpus = caps.get("gpus") if isinstance(caps.get("gpus"), list) else []
        node_vram = sum(float(gpu.get("vram_total_gb") or 0.0) for gpu in gpus if isinstance(gpu, dict))
        total_vram += node_vram
        if node_vram > 0:
            gpu_nodes += 1
    candidate_models = [
        {"model": model, "estimated_ram_gb": required, "fits_aggregate_ram": total_ram >= required}
        for model, required in ModelRouter.MODEL_RAM_GB.items()
    ]
    runnable_by_sum = [item for item in candidate_models if item["fits_aggregate_ram"]]
    missing: list[str] = []
    if total_ram < 4:
        missing.append("RAM federada autorizada >= 4 GB para modelos 3B por suma")
    if total_ram < 8:
        missing.append("RAM federada autorizada >= 8 GB para 7B/8B por suma")
    if gpu_nodes == 0:
        missing.append("GPU/VRAM federada reportada por app nativa")
    missing.append("runtime distribuido de inferencia para sumar RAM entre dispositivos (llama.cpp RPC/worker propio)")
    return {
        "device_count": len(feeders),
        "runtime_node_count": len(runtime_ready),
        "cpu_authorized_count": total_cpu,
        "ram_authorized_gb": total_ram,
        "ram_available_gb": total_available_ram,
        "vram_authorized_gb": round(total_vram, 2),
        "gpu_node_count": gpu_nodes,
        "can_parallel_feed": bool(feeders),
        "can_run_single_llm_by_sum": False,
        "runtime": "active_job_runtime" if runtime_ready else "pending_distributed_inference_runtime",
        "active_job_runtime": bool(runtime_ready),
        "supported_runtime_tasks": sorted({
            task
            for node in runtime_ready
            for task in (((node.get("capabilities") or {}).get("allowed_tasks") or []))
            if task in {"preprocess_text", "federated_inference_probe", "android_model_doctor", "android_local_generate"}
        }),
        "runnable_by_aggregate_ram": runnable_by_sum,
        "candidate_models": candidate_models,
        "missing_for_real_distributed_models": missing,
        "note": "Runtime por jobs activo para preproceso/probes si hay nodos compatibles; no equivale a RAM compartida de Ollama ni a inferencia tensor-paralela.",
    }


def federation_resource_lease(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    leases = []
    totals = {
        "devices": 0,
        "direct_lan_devices": 0,
        "relay_devices": 0,
        "cpu_authorized_count": 0,
        "ram_authorized_gb": 0.0,
        "ram_available_gb": 0.0,
        "llm_hosts": 0,
    }
    for node in nodes:
        if not (node.get("can_feed_local_models") and node.get("federation_complete")):
            continue
        caps = node.get("capabilities") or {}
        relay_url = str(caps.get("relay_url") or "")
        transport = "lan_8010" if ("127.0.0.1:8010" in relay_url or "localhost:8010" in relay_url or "192.168." in relay_url) else "public_relay"
        cpu_authorized = int(node.get("cpu_authorized_count") or 0)
        ram_authorized = round(float(node.get("ram_authorized_gb") or 0.0), 2)
        ram_available = round(float(node.get("ram_available_gb") or 0.0), 2)
        tasks = caps.get("allowed_tasks") if isinstance(caps.get("allowed_tasks"), list) else []
        lease = {
            "node_id": node.get("node_id"),
            "name": node.get("name"),
            "transport": transport,
            "online": node.get("online"),
            "app_version": caps.get("app_version"),
            "device": caps.get("device"),
            "resource_limit_percent": node.get("resource_limit_percent"),
            "resource_limit_reported": node.get("resource_limit_reported"),
            "cpu_authorized_count": cpu_authorized,
            "ram_authorized_gb": ram_authorized,
            "ram_available_gb": ram_available,
            "ram_total_gb": caps.get("ram_total_gb"),
            "memory_class_mb": caps.get("memory_class_mb"),
            "large_memory_class_mb": caps.get("large_memory_class_mb"),
            "java_heap_max_gb": caps.get("java_heap_max_gb"),
            "native_large_heap_requested": bool(caps.get("native_large_heap_requested")),
            "edge_model_runtime": node.get("edge_model_runtime"),
            "model_runtime_backend": node.get("model_runtime_backend"),
            "can_host_llm": node.get("can_host_llm"),
            "allowed_tasks": tasks,
            "lease_status": "llm_host_ready" if node.get("can_host_llm") else ("job_worker_ready" if tasks else "heartbeat_only"),
        }
        leases.append(lease)
        totals["devices"] += 1
        totals["direct_lan_devices"] += 1 if transport == "lan_8010" else 0
        totals["relay_devices"] += 1 if transport == "public_relay" else 0
        totals["cpu_authorized_count"] += cpu_authorized
        totals["ram_authorized_gb"] += ram_authorized
        totals["ram_available_gb"] += ram_available
        totals["llm_hosts"] += 1 if node.get("can_host_llm") else 0
    totals["ram_authorized_gb"] = round(totals["ram_authorized_gb"], 2)
    totals["ram_available_gb"] = round(totals["ram_available_gb"], 2)
    return {
        "status": "ok",
        "mode": "federation-resource-lease",
        "totals": totals,
        "leases": leases,
        "truth": "Estos recursos son arrendables por jobs federados o modelos Android reales; no son RAM unificada de Ollama hasta tener runtime distribuido tensor-paralelo.",
    }


def build_model_capacity(sync_relay: bool = False) -> dict[str, Any]:
    hardware, ollama = system_payload()
    matrix = ModelCompatibilityMatrix(hardware=hardware, available_models=ollama.get("models", [])).build()
    federation = Federation()
    relay = relay_settings()
    relay_sync: dict[str, Any] = {"attempted": False}
    if sync_relay and relay.get("admin_token"):
        try:
            relay_sync = PublicRelayClient(str(relay["url"]), str(relay["admin_token"]), timeout=12).sync_nodes_to_federation(federation)
            relay_sync["attempted"] = True
        except Exception as exc:  # pragma: no cover - depends on public network
            relay_sync = {"attempted": True, "status": "error", "error": str(exc)}
    nodes = [node_model_readiness(node) for node in federation.list_nodes(status="active")]
    online_feeders = [node for node in nodes if node["can_feed_local_models"] and node["federation_complete"]]
    federated_authorized = federated_model_plan(nodes)
    resource_lease = federation_resource_lease(nodes)
    recommended = [item for item in matrix["models"] if item["status"] == "recommended"]
    allowed = [item for item in matrix["models"] if item["status"] == "allowed"]
    blocked = [item for item in matrix["models"] if item["status"] == "blocked"]
    local_missing: list[str] = []
    if not ollama.get("ok"):
        local_missing.append("Ollama local activo")
    if hardware.ram_available_gb < 4:
        local_missing.append("RAM libre >= 4 GB para modelos 3B")
    if hardware.ram_available_gb < 8:
        local_missing.append("RAM libre >= 8 GB para modelos 7B/8B")
    if not any(gpu.cuda_available or gpu.vram_total_gb > 0 for gpu in hardware.gpus):
        local_missing.append("GPU/VRAM detectable para acelerar modelos")
    if not recommended:
        local_missing.append("modelos instalados compatibles/recomendados")
    docker = docker_status()
    return {
        "status": "ok",
        "mode": "model-capacity",
        "local": {
            "hardware": hardware.to_dict(),
            "ollama": ollama,
            "docker": docker,
            "python": tool_status("python", ["python", "--version"]),
            "node": tool_status("node", ["node", "-v"]),
            "model_matrix_summary": matrix["summary"],
            "counts": matrix["counts"],
            "recommended_models": recommended,
            "allowed_models": allowed,
            "blocked_models": blocked,
            "missing_for_comfortable_models": local_missing,
        },
        "federation": {
            "relay": {"url": relay.get("url"), "has_admin_token": bool(relay.get("admin_token")), "sync": relay_sync},
            "nodes": nodes,
            "online_feeders": online_feeders,
            "authorized": federated_authorized,
            "resource_lease": resource_lease,
            "llm_hosts": [node for node in nodes if node["can_host_llm"]],
        },
        "constants": {
            "router": "single-port ModelRouter activo en /api/router/doctor",
            "docker": "motor activo" if docker["ok"] else ("instalado, motor pendiente" if docker["installed"] else "pendiente/no disponible"),
            "relay": "public relay Railway",
            "policy": "solo dispositivos nativos/autorizados que invierten CPU/RAM/GPU cuentan como nodos federados",
            "distributed_runtime": "jobs Android nativos: preprocess_text y federated_inference_probe alimentan al modelo local",
        },
    }




def _edge_llm_host_snapshot() -> list[dict]:
    """Hosts LLM edge detectados por el router federado.

    Fuente secundaria para evitar falsos '0 hosts' cuando el resource lease
    autorizado todavía no consolidó el estado, pero el EdgeRouter sí ve el nodo.
    """
    try:
        nodes = EdgeRouter().list_edge_llm_nodes()
    except Exception:
        return []

    out = []
    for node in nodes:
        if not node.is_ready:
            continue
        out.append({
            "node_id": node.node_id,
            "name": node.name,
            "online": node.online,
            "can_host_llm": node.can_host_llm,
            "lease_status": node.lease_status,
            "transport": node.transport,
            "edge_cpu_threads_available": node.edge_cpu_threads_available,
            "edge_ram_available_gb": node.edge_ram_available_gb,
            "model_runtime_backend": node.model_runtime_backend,
        })
    return out


def _edge_llm_host_count(authorized: dict, federation: dict) -> int:
    authorized_count = int((authorized or {}).get("llm_hosts") or 0)
    if authorized_count > 0:
        return authorized_count
    llm_hosts = (federation or {}).get("llm_hosts") or []
    if isinstance(llm_hosts, list) and len(llm_hosts) > 0:
        return len(llm_hosts)
    return len(_edge_llm_host_snapshot())


def _pulse_item(name: str, ok: bool, summary: str, detail: dict[str, Any] | None = None, level: str | None = None) -> dict[str, Any]:
    clean_level = level or ("ok" if ok else "warn")
    return {"name": name, "ok": ok, "level": clean_level, "summary": summary, "detail": detail or {}}


def _safe_pulse(name: str, fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return _pulse_item(name, False, str(exc), level="error")


def _experimental_neuron_pulse() -> dict[str, Any]:
    """Resumen seguro de neuronas experimentales para Pulso Vivo."""
    try:
        ledger = build_experimental_evidence_ledger(runs_dir="runs", limit=200)
        neurons = ledger.get("neurons") or []
        stable_ready = [n for n in neurons if n.get("stable_promotion_ready")]
        return {
            "ok": True,
            "summary": ledger.get("summary", {}),
            "last_active_neuron": neurons[0].get("name") if neurons else None,
            "stable_ready_count": len(stable_ready),
            "neurons": [
                {
                    "name": n.get("name"),
                    "status": n.get("status"),
                    "domain": n.get("domain"),
                    "activation_count": n.get("activation_count"),
                    "diagnosis_count": n.get("diagnosis_count"),
                    "test_plan_count": n.get("test_plan_count"),
                    "last_run_id": n.get("last_run_id"),
                    "stable_promotion_ready": n.get("stable_promotion_ready"),
                }
                for n in neurons[:5]
            ],
            "policy": "evidence_only_no_auto_promotion",
        }
    except Exception as exc:
        return {
            "ok": False,
            "summary": {"experimental_neurons_with_evidence": 0, "total_activations": 0},
            "last_active_neuron": None,
            "stable_ready_count": 0,
            "neurons": [],
            "error": str(exc),
            "policy": "evidence_only_no_auto_promotion",
        }


def _stable_readiness_pulse() -> dict[str, Any]:
    """Resumen seguro de readiness stable para Pulso Vivo.

    No promueve neuronas. Solo informa si alguna experimental tiene evidencia
    suficiente para revisión humana futura.
    """
    try:
        report = evaluate_stable_readiness(runs_dir="runs", limit=300)
        neurons = report.get("neurons") or []
        return {
            "ok": True,
            "summary": report.get("summary", {}),
            "ready_neurons": [
                {
                    "name": n.get("name"),
                    "status": n.get("status"),
                    "domain": n.get("domain"),
                    "activation_count": n.get("activation_count"),
                    "diagnosis_count": n.get("diagnosis_count"),
                    "test_plan_count": n.get("test_plan_count"),
                    "last_run_id": n.get("last_run_id"),
                    "required_human_decision": n.get("required_human_decision"),
                }
                for n in neurons
                if n.get("ready_for_stable_review")
            ][:5],
            "blocked_neurons": [
                {
                    "name": n.get("name"),
                    "status": n.get("status"),
                    "domain": n.get("domain"),
                    "blockers": n.get("blockers", []),
                    "last_run_id": n.get("last_run_id"),
                }
                for n in neurons
                if not n.get("ready_for_stable_review")
            ][:5],
            "policy": "readiness_only_no_auto_stable",
        }
    except Exception as exc:
        return {
            "ok": False,
            "summary": {
                "neurons_evaluated": 0,
                "ready_for_stable_review": 0,
                "not_ready": 0,
                "policy": "readiness_only_no_auto_stable",
            },
            "ready_neurons": [],
            "blocked_neurons": [],
            "error": str(exc),
            "policy": "readiness_only_no_auto_stable",
        }


def build_system_pulse(sync_relay: bool = True, intent: str = "conversation", urgency: str = "medium") -> dict[str, Any]:
    return build_system_pulse_core(
        sync_relay=sync_relay,
        intent=intent,
        urgency=urgency,
        build_model_capacity_fn=build_model_capacity,
        router_payload_fn=router_payload,
        model_install_queue_fn=model_install_queue,
        semantic_governance_doctor_fn=semantic_governance_doctor,
        federated_transport_doctor_fn=federated_transport_doctor,
        life_snapshot_fn=LIFE_PULSE.snapshot,
        qualia_snapshot_fn=QUALIA.snapshot,
        edge_llm_host_count_fn=_edge_llm_host_count,
        edge_llm_host_snapshot_fn=_edge_llm_host_snapshot,
    )


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, Any]:
    LIFE_PULSE.record_action("health")
    runner = TriadeRunner(use_ollama=False)
    hardware, ollama = system_payload()
    return {
        "status": "ok", "entity": "Tríade Ω", "mode": "single-port", "port": 8010,
        "security": {"api_key_required": bool(os.getenv("TRIADE_API_KEY"))},
        "repo": repo_info(), "hardware": hardware.to_dict(), "ollama": ollama, "doctor": runner.doctor(),
    }


@app.post("/api/router/doctor")
def route_doctor(request: RouterRequest) -> dict[str, Any]:
    LIFE_PULSE.record_action("router_doctor")
    return router_payload(intent=request.intent, urgency=request.urgency)


@app.get("/api/models/compatibility")
def model_compatibility() -> dict[str, Any]:
    LIFE_PULSE.record_action("model_compatibility")
    hardware, ollama = system_payload()
    matrix = ModelCompatibilityMatrix(hardware=hardware, available_models=ollama.get("models", []))
    return {"status": "ok", "mode": "single-port", "ollama": ollama, "matrix": matrix.build()}


@app.get("/api/models/install-queue")
def model_install_queue(include_allowed: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("model_install_queue")
    hardware, ollama = system_payload()
    queue = ModelInstallQueue(hardware=hardware, available_models=ollama.get("models", []))
    return queue.build(include_allowed=include_allowed)


@app.get("/api/system/model-capacity")
def system_model_capacity(sync_relay: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("model_capacity")
    return build_model_capacity(sync_relay=sync_relay)


@app.get("/api/system/pulse")
def system_pulse(sync_relay: bool = True, intent: str = "conversation", urgency: str = "medium") -> dict[str, Any]:
    LIFE_PULSE.record_action("system_pulse")
    return build_system_pulse(sync_relay=sync_relay, intent=intent, urgency=urgency)





@app.get("/api/ui/clean", response_class=HTMLResponse)
def clean_ui() -> str:
    """Vista limpia experimental de la consola 8010.

    Se alimenta desde /api/ui/manifest y endpoints vivos.
    """
    return """
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Tríade Ω · Consola limpia</title>
<style>
:root{color-scheme:dark;--bg:#090b10;--panel:#121722;--panel2:#171d28;--line:#293244;--text:#eef4ff;--muted:#9aa7bd;--ok:#82e69a;--warn:#ffd166;--bad:#ff7b7b;--accent:#7cc7ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif}
.app{min-height:100vh;display:grid;grid-template-columns:310px minmax(420px,1fr) 380px}
aside,main{min-width:0}.left,.right{background:var(--panel);border-color:var(--line);overflow:auto}.left{border-right:1px solid var(--line);padding:16px}.right{border-left:1px solid var(--line);padding:16px}
.center{display:flex;flex-direction:column;background:#0b0f16}.top{border-bottom:1px solid var(--line);padding:14px 16px;display:flex;justify-content:space-between;gap:12px;align-items:center}
h1{font-size:22px;margin:0}h2{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#cbd7ea;margin:0 0 10px}.muted,.small{color:var(--muted)}.small{font-size:12px;line-height:1.4}
.section{border-top:1px solid var(--line);margin-top:15px;padding-top:13px}.card,.box{background:var(--panel2);border:1px solid var(--line);border-radius:10px;padding:10px;margin-top:8px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric b{display:block;font-size:20px}.metric span{font-size:12px;color:var(--muted)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.pill{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:4px 8px;margin:3px;font-size:12px}
button,.btn{width:100%;border:0;border-radius:9px;padding:10px;margin-top:8px;background:var(--accent);color:#061018;font-weight:850;cursor:pointer;text-decoration:none;display:inline-flex;justify-content:center}
button.secondary,.btn.secondary{background:#222b3a;color:var(--text);border:1px solid var(--line)}button:disabled{opacity:.45;cursor:not-allowed}
label{display:block;font-size:12px;color:var(--muted);margin:10px 0 5px}input,select,textarea{width:100%;background:#171f2e;color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px}textarea{resize:vertical;min-height:58px}
.chat{flex:1;overflow:auto;padding:16px}.msg{padding:12px;border-radius:10px;margin:10px 0;white-space:pre-wrap;line-height:1.45}.user{background:#1d5fc0;margin-left:14%}.bot{background:#151d29;border:1px solid var(--line);margin-right:14%}.meta{font-size:12px;color:var(--muted);margin-top:7px}
.composer{display:grid;grid-template-columns:1fr 110px;gap:10px;padding:14px;border-top:1px solid var(--line)}.composer button{margin:0}.log{white-space:pre-wrap;max-height:260px;overflow:auto;font-size:12px}
@media(max-width:1100px){.app{grid-template-columns:1fr}.left,.right{border:0;border-bottom:1px solid var(--line)}.center{min-height:70vh}.composer{grid-template-columns:1fr}.user,.bot{margin-left:0;margin-right:0}}
</style>
</head>
<body>
<div class="app">
  <aside class="left">
    <h1>Tríade Ω</h1>
    <p class="small">Consola limpia · datos vivos primero · sin botones falsos.</p>
    <div id="session"></div>
    <div id="actions"></div>
    <div id="downloads"></div>
  </aside>

  <main class="center">
    <div class="top">
      <div><b>Chat local auditable</b><br><span id="status" class="muted">Cargando manifest...</span></div>
      <div id="globalPills"></div>
    </div>
    <section id="chat" class="chat"></section>
    <div class="composer">
      <textarea id="msg" placeholder="Escribe... Ctrl+Enter"></textarea>
      <button id="sendBtn">Enviar</button>
    </div>
  </main>

  <aside class="right">
    <section class="section"><h2>Estado vivo</h2><div id="live"></div></section>
    <section class="section"><h2>Neuronas</h2><div id="neurons"></div></section>
    <section class="section"><h2>Diagnóstico</h2><div id="diagnostics"></div></section>
    <section class="section"><h2>Salida</h2><div id="box" class="box log">Sin consultar.</div></section>
  </aside>
</div>

<script>
const $ = id => document.getElementById(id);
const state = {manifest:null, pulse:null, capacity:null, neurons:null, busy:false};
function setStatus(t, ok=false){$('status').textContent=t; $('status').className=ok?'ok':'muted'}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
async function api(url, opts={}){const r=await fetch(url,opts);const j=await r.json();if(!r.ok)throw Error(j.detail||r.status);return j}
function section(id){return state.manifest.sections.find(s=>s.id===id)}
function field(id){return document.querySelector(`[data-field="${id}"]`)}

function renderSession(){
  const s=section('session');
  $('session').innerHTML='<div class="section"><h2>'+esc(s.title)+'</h2>'+s.fields.map(f=>{
    if(f.type==='select') return `<label>${esc(f.label)}</label><select data-field="${f.id}">${f.options.map(o=>`<option>${esc(o)}</option>`).join('')}</select>`;
    if(f.type==='checkbox') return `<label><input data-field="${f.id}" type="checkbox"> ${esc(f.label)}</label>`;
    return `<label>${esc(f.label)}</label><input data-field="${f.id}" type="${esc(f.type||'text')}">`;
  }).join('')+'</div>';
  const intent=field('intent'); if(intent) intent.value='conversation';
  const urgency=field('urgency'); if(urgency) urgency.value='medium';
  const auto=field('auto_select_models'); if(auto) auto.checked=true;
}

function renderActions(){
  const s=section('actions');
  $('actions').innerHTML='<div class="section"><h2>'+esc(s.title)+'</h2>'+s.items.map(a=>{
    if(a.id==='send') return '';
    return `<button class="secondary" disabled title="${esc(a.disabled_reason||'Acción no disponible')}">${esc(a.label)}</button><div class="small">${esc(a.disabled_reason||'')}</div>`;
  }).join('')+'</div>';
}

function renderDownloads(){
  const s=section('downloads');
  $('downloads').innerHTML='<div class="section"><h2>'+esc(s.title)+'</h2>'+s.items.map(i=>`<a class="btn secondary" href="${esc(i.href)}">${esc(i.label)}</a>`).join('')+'</div>';
}

function renderLive(){
  const p=state.pulse||{}, c=state.capacity||{};
  const summary=p.summary||'Sin pulso';
  const checks=(p.checks||[]).slice(0,6).map(x=>`<span class="pill ${x.level==='ok'?'ok':x.level==='error'?'bad':'warn'}">${esc(x.name)}: ${esc(x.level)}</span>`).join('');
  const h=c.local?.hardware||{};
  $('live').innerHTML=`<div class="grid">
    <div class="card metric"><b>${esc(p.level||'?')}</b><span>${esc(summary)}</span></div>
    <div class="card metric"><b>${esc(h.ram_available_gb??'?')}</b><span>GB RAM libre</span></div>
  </div><div class="card">${checks||'<span class="muted">Sin checks.</span>'}</div>`;
  $('globalPills').innerHTML=`<span class="pill ${p.level==='ok'?'ok':'warn'}">${esc(p.mode||'sin pulso')}</span>`;
}

function renderNeurons(){
  const n=state.neurons||{};
  const list=n.neurons||[];
  $('neurons').innerHTML=`<div class="grid">
    <div class="card metric"><b>${n.summary?.total_neurons??0}</b><span>Total</span></div>
    <div class="card metric"><b>${n.summary?.ready_for_stable_review??0}</b><span>Ready stable</span></div>
  </div>` + list.slice(0,6).map(x=>`<div class="card">
    <b>${esc(x.name)}</b><br><span class="small">${esc(x.status)} · ${esc(x.domain)}</span>
    <div class="small">act:${x.evidence?.activation_count||0} diag:${x.evidence?.diagnosis_count||0} tests:${x.evidence?.test_plan_count||0}</div>
    ${(x.ui_actions||[]).map(a=>`<button class="secondary" disabled="${!a.enabled}" title="${esc(a.disabled_reason||'')}">${esc(a.label)}</button>`).join('')}
  </div>`).join('');
}

function renderDiagnostics(){
  const d=section('diagnostics');
  $('diagnostics').innerHTML=d.items.map(i=>`<button class="secondary" onclick="runDiagnostic('${esc(i.id)}')">${esc(i.label)}</button>`).join('');
}

async function runDiagnostic(id){
  const item=section('diagnostics').items.find(x=>x.id===id);
  if(!item) return;
  try{
    setStatus('Consultando '+item.label+'...');
    let opts={method:item.method||'GET',headers:{'Content-Type':'application/json'}};
    if(item.method==='POST'){
      opts.body=JSON.stringify({intent:field('intent')?.value||'conversation',urgency:field('urgency')?.value||'medium',wait_timeout:35});
    }
    const j=await api(item.endpoint,opts);
    $('box').textContent=JSON.stringify(j,null,2);
    setStatus(item.label+' OK',true);
  }catch(e){$('box').textContent='Error: '+e.message;setStatus(item.label+' falló')}
}

function add(role,text,meta=''){
  const div=document.createElement('div');
  div.className='msg '+role;
  div.textContent=text;
  if(meta){const m=document.createElement('div');m.className='meta';m.textContent=meta;div.appendChild(m)}
  $('chat').appendChild(div); $('chat').scrollTop=$('chat').scrollHeight;
}

async function send(){
  const text=$('msg').value.trim(); if(!text||state.busy)return;
  state.busy=true; $('sendBtn').disabled=true; $('msg').value=''; add('user',text); setStatus('Procesando...');
  try{
    const payload={text,source:'clean-ui',use_ollama:field('use_ollama')?.checked||false,auto_select_models:field('auto_select_models')?.checked||true,hypothalamus_model:field('hypothalamus_model')?.value||null,central_model:field('central_model')?.value||null,context:{intent:field('intent')?.value,urgency:field('urgency')?.value}};
    const j=await api('/api/run',{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':field('api_key')?.value||''},body:JSON.stringify(payload)});
    add('bot',j.response||'(sin respuesta)',[j.run_id,j.models?.hypothalamus?.name,j.models?.central?.name].filter(Boolean).join(' · '));
    setStatus('Respuesta recibida',true); await refresh();
  }catch(e){add('bot','Error: '+e.message);setStatus('Error')}
  state.busy=false; $('sendBtn').disabled=false;
}

async function refresh(){
  try{
    state.pulse=await api('/api/system/pulse?sync_relay=true');
    state.capacity=await api('/api/system/model-capacity?sync_relay=true');
    state.neurons=await api('/api/system/neurons?limit=50');
    renderLive(); renderNeurons();
  }catch(e){$('box').textContent='Refresh falló: '+e.message}
}

async function init(){
  state.manifest=await api('/api/ui/manifest');
  renderSession(); renderActions(); renderDownloads(); renderDiagnostics();
  $('sendBtn').onclick=send; $('msg').addEventListener('keydown',e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))send()});
  add('bot','Tríade Ω lista en vista limpia. Datos vivos primero, acciones humanas bloqueadas hasta endpoint real.');
  await refresh(); setInterval(refresh,15000);
}
init().catch(e=>{setStatus('Error inicial: '+e.message);});
</script>
</body>
</html>
"""

@app.get("/api/ui/manifest")
def ui_manifest() -> dict[str, Any]:
    """Contrato dinámico de la interfaz 8010.

    No ejecuta acciones. Define secciones, endpoints y política visual.
    """
    LIFE_PULSE.record_action("ui_manifest")
    return build_ui_manifest()

@app.get("/api/system/neurons")
def system_neurons(limit: int = 100) -> dict[str, Any]:
    """Estado vivo de neuronas para UI.

    Solo lectura: no aprueba, no promueve, no ejecuta acciones.
    """
    LIFE_PULSE.record_action("system_neurons")
    return build_neuron_dashboard(limit=limit)

@app.get("/api/system/life")
def system_life(tick: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("life_snapshot")
    if tick:
        return LIFE_PULSE.tick()
    return LIFE_PULSE.snapshot()


@app.get("/api/system/qualia")
def system_qualia(refresh_life: bool = False) -> dict[str, Any]:
    LIFE_PULSE.record_action("qualia_snapshot")
    return QUALIA.snapshot(refresh_life=refresh_life)


@app.get("/api/federation/resource-lease")
def federation_resource_lease_endpoint(sync_relay: bool = True) -> dict[str, Any]:
    capacity = build_model_capacity(sync_relay=sync_relay)
    lease = capacity["federation"]["resource_lease"]
    lease["local"] = {
        "hardware": capacity["local"]["hardware"],
        "ollama": capacity["local"]["ollama"],
        "docker": capacity["local"]["docker"],
    }
    return lease


@app.get("/downloads/triade-android-node.apk")
def download_android_node_apk() -> FileResponse:
    if not ANDROID_APK_PATH.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="APK Android no encontrado.")
    return FileResponse(
        ANDROID_APK_PATH,
        media_type="application/vnd.android.package-archive",
        filename="triade-android-node.apk",
    )


@app.get("/downloads/android/runtime-manifest")
def android_runtime_manifest() -> dict[str, Any]:
    llama_ready = ANDROID_LLAMA_CLI_PATH.exists()
    model_ready = ANDROID_BASE_MODEL_PATH.exists()
    return {
        "status": "ok" if llama_ready and model_ready else "incomplete",
        "mode": "android-runtime-bootstrap",
        "llama_cli": {
            "ready": llama_ready,
            "url": "/downloads/android/llama-cli",
            "expected_path": str(ANDROID_LLAMA_CLI_PATH),
            "install_target": "APK private bin/llama-cli",
        },
        "base_model": {
            "ready": model_ready,
            "url": "/downloads/android/base-model.gguf",
            "expected_path": str(ANDROID_BASE_MODEL_PATH),
            "install_target": "APK private models/triade-base.gguf",
        },
        "termux_bootstrap": {
            "url": "/downloads/android/termux-bootstrap.sh",
            "note": "La APK no puede ejecutar comandos dentro de Termux; el usuario debe abrir Termux y ejecutar el script si quiere preparar ese entorno.",
        },
        "truth": "8010 sirve los artefactos si existen localmente. No descarga modelos con licencia por su cuenta ni instala paquetes en Termux desde otra app.",
    }


@app.get("/downloads/android/llama-cli")
def download_android_llama_cli() -> FileResponse:
    if not ANDROID_LLAMA_CLI_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"llama-cli Android no encontrado. Coloca el binario arm64 en {ANDROID_LLAMA_CLI_PATH}.",
        )
    return FileResponse(ANDROID_LLAMA_CLI_PATH, media_type="application/octet-stream", filename="llama-cli")


@app.get("/downloads/android/base-model.gguf")
def download_android_base_model() -> FileResponse:
    if not ANDROID_BASE_MODEL_PATH.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Modelo base GGUF no encontrado. Coloca un modelo pequeno en {ANDROID_BASE_MODEL_PATH}.",
        )
    return FileResponse(ANDROID_BASE_MODEL_PATH, media_type="application/octet-stream", filename="triade-base.gguf")


@app.get("/downloads/android/termux-bootstrap.sh", response_class=PlainTextResponse)
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


@app.post("/api/register")
def local_node_register(request: LocalNodeRegisterRequest) -> dict[str, Any]:
    node_id = "local-" + secrets.token_hex(5)
    node_token = secrets.token_urlsafe(24)
    tokens = load_local_node_tokens()
    tokens[node_id] = node_token
    save_local_node_tokens(tokens)
    node = upsert_local_android_node(node_id, request.display_name, request.capabilities)
    return {"status": "ok", "node_id": node_id, "node_token": node_token, "node": node, "capabilities": node["capabilities"]}


@app.post("/api/heartbeat")
def local_node_heartbeat(request: LocalNodeHeartbeatRequest) -> dict[str, Any]:
    tokens = load_local_node_tokens()
    known = tokens.get(request.node_id)
    if known and request.node_token != known:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de nodo inválido.")
    if not known:
        tokens[request.node_id] = request.node_token or secrets.token_urlsafe(24)
        save_local_node_tokens(tokens)
    node = upsert_local_android_node(request.node_id, request.node_id, request.capabilities)
    return {"status": "ok", "node": node}


@app.get("/api/jobs/next")
def local_node_next_job(node_id: str, node_token: str = "") -> dict[str, Any]:
    tokens = load_local_node_tokens()
    if tokens.get(node_id) and tokens[node_id] != node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de nodo inválido.")
    for job in LOCAL_JOBS.values():
        if job.get("node_id") == node_id and job.get("status") == "pending":
            job["status"] = "running"
            job["updated_at"] = time.time()
            return {"status": "ok", "node_id": node_id, "job": job}
    return {"status": "idle", "node_id": node_id, "job": None}


@app.get("/api/federation/transport/doctor")
def federated_transport_doctor() -> dict[str, Any]:
    doctor = FederatedTransportDoctor()
    return doctor.model_dump() if hasattr(doctor, "model_dump") else doctor.dict()


@app.post("/api/federation/transport/next")
def federated_transport_next(envelope: SignedEnvelope) -> dict[str, Any]:
    verify_signed_node_envelope(envelope)
    for job in LOCAL_JOBS.values():
        if job.get("node_id") == envelope.node_id and job.get("status") == "pending":
            ensure_sandbox_task(str(job.get("task") or ""))
            job["status"] = "running"
            job["updated_at"] = time.time()
            return {"status": "ok", "node_id": envelope.node_id, "job": job}
    return {"status": "idle", "node_id": envelope.node_id, "job": None}


@app.post("/api/jobs/{job_id}/result")
def local_node_job_result(job_id: str, request: LocalNodeJobResultRequest) -> dict[str, Any]:
    tokens = load_local_node_tokens()
    if tokens.get(request.node_id) and tokens[request.node_id] != request.node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token de nodo inválido.")
    job = LOCAL_JOBS.setdefault(job_id, {"job_id": job_id, "node_id": request.node_id})
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
                capabilities["benchmark_score"] = int(request.result.get("score") or capabilities.get("benchmark_score") or 0)
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
                capabilities["model_runtime_backend"] = request.result.get("backend") or capabilities.get("model_runtime_backend") or "none"
                capabilities["can_run_local_llm"] = bool(request.result.get("can_run_local_llm"))
                capabilities["local_model_runtime_ready"] = bool(request.result.get("native_backend_present") and request.result.get("can_run_local_llm"))
                capabilities["available_local_models"] = request.result.get("available_models") or capabilities.get("available_local_models") or []
                capabilities["supported_model_formats"] = request.result.get("supported_model_formats") or capabilities.get("supported_model_formats") or []
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
                    capabilities["model_runtime_backend"] = request.result.get("backend") or capabilities.get("model_runtime_backend")
                    capabilities = local_node_capabilities(request.node_id, capabilities)
            capabilities["compute_status"] = "ready"
            capabilities["distributed_runtime_status"] = "active"
            federation.update_capabilities(request.node_id, capabilities)
    return {"status": "ok", "job_id": job_id, "accepted": True}


@app.post("/api/federation/transport/result")
def federated_transport_result(envelope: SignedEnvelope) -> dict[str, Any]:
    verify_signed_node_envelope(envelope)
    payload = FederatedJobResultPayload(**envelope.payload)
    return local_node_job_result(
        payload.job_id,
        LocalNodeJobResultRequest(
            node_id=envelope.node_id,
            node_token=load_local_node_tokens().get(envelope.node_id, ""),
            status=payload.status,
            result=payload.result,
            error=payload.error,
        ),
    )


@app.post("/api/local-federation/benchmark")
def local_federation_benchmark(seconds: float = 1.0, wait_timeout: float = 25.0) -> dict[str, Any]:
    nodes = local_federated_nodes("browser_benchmark")
    if not nodes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay dispositivos federados locales online.")
    node = nodes[0]
    job = create_local_job(str(node["node_id"]), task="browser_benchmark", seconds=seconds)
    result = wait_local_job(str(job["job_id"]), timeout=wait_timeout)
    return {"status": "ok" if result.get("status") == "completed" else result.get("status"), "node_id": node["node_id"], "job": result}


@app.get("/api/distributed-runtime/status")
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
        if active else "Pendiente: conecta la app Android directamente al 8010/LAN para que tome jobs locales. La inferencia LLM tensor-paralela sigue pendiente.",
    }


@app.post("/api/distributed-runtime/preprocess")
def distributed_runtime_preprocess(request: DistributedRuntimeRequest) -> dict[str, Any]:
    nodes = local_federated_nodes("preprocess_text")
    if not nodes:
        relay = relay_settings()
        if relay.get("admin_token"):
            federation = Federation()
            result = PublicRelayClient(str(relay["url"]), str(relay["admin_token"]), timeout=12).preprocess_text_online(
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
                    "nodes_used": [item.get("node_id") for item in result.get("results", [])],
                    "jobs": result.get("results", []),
                    "model_feed": result.get("model_feed", {}),
                    "truth": "Preproceso ejecutado por relay publico porque no hay nodos LAN directos al 8010.",
                }
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay nodos Android locales con preprocess_text online ni respuesta util via relay publico.")
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
    results = [wait_local_job(str(job["job_id"]), timeout=request.wait_timeout) for job in jobs]
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


@app.post("/api/distributed-runtime/probe")
def distributed_runtime_probe(request: DistributedProbeRequest) -> dict[str, Any]:
    nodes = local_federated_nodes("federated_inference_probe")
    if not nodes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay nodos Android locales con federated_inference_probe online.")
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
    results = [wait_local_job(str(job["job_id"]), timeout=request.wait_timeout) for job in jobs]
    completed = [job for job in results if job.get("status") == "completed"]
    return {
        "status": "ok" if completed else "degraded",
        "mode": "distributed-runtime",
        "task": "federated_inference_probe",
        "submitted": len(jobs),
        "completed": len(completed),
        "total_ops": sum(int((job.get("result") or {}).get("ops") or 0) for job in completed),
        "jobs": results,
        "truth": "Probe ejecutado en Android. Aun no es inferencia LLM tensor-paralela ni memoria unificada de Ollama.",
    }


@app.post("/api/distributed-runtime/android-model-doctor")
def distributed_runtime_android_model_doctor(request: DistributedModelDoctorRequest) -> dict[str, Any]:
    nodes = local_federated_nodes("android_model_doctor")
    jobs = []
    transport = "lan_8010"
    if nodes:
        for node in nodes:
            jobs.append(create_local_job(str(node["node_id"]), task="android_model_doctor", seconds=1.0))
        results = [wait_local_job(str(job["job_id"]), timeout=request.wait_timeout) for job in jobs]
    else:
        relay = relay_settings()
        results = []
        transport = "public_relay_fallback"
        if relay.get("admin_token"):
            federation = Federation()
            client = PublicRelayClient(str(relay["url"]), str(relay["admin_token"]), timeout=12)
            sync = client.sync_nodes_to_federation(federation)
            for node in sync.get("nodes", []):
                capabilities = node.get("capabilities") or {}
                if not capabilities.get("online") or "android_model_doctor" not in capabilities.get("allowed_tasks", []):
                    continue
                job_id = client.create_job(str(node["node_id"]), task="android_model_doctor", seconds=1.0)
                results.append({"job_id": job_id, "node_id": node["node_id"], "job": client.wait_for_job(job_id, timeout=request.wait_timeout)})
    completed = [item for item in results if (item.get("status") == "completed" or (item.get("job") or {}).get("status") == "completed")]
    doctors = [(item.get("result") or (item.get("job") or {}).get("result") or {}) for item in completed]
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


@app.post("/api/distributed-runtime/android-local-generate")
def distributed_runtime_android_local_generate(request: AndroidLocalGenerateRequest) -> dict[str, Any]:
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

    local_nodes = android_llm_host_nodes(local_federated_nodes("android_local_generate"))
    if request.node_id:
        local_nodes = [node for node in local_nodes if str(node.get("node_id")) == request.node_id]
    if local_nodes:
        node = local_nodes[0]
        job = create_local_job(str(node["node_id"]), task="android_local_generate", payload=payload, seconds=1.0)
        result = wait_local_job(str(job["job_id"]), timeout=request.wait_timeout)
        completed = result.get("status") == "completed" and bool((result.get("result") or {}).get("ok"))
        return {
            "status": "ok" if completed else result.get("status", "degraded"),
            "mode": "distributed-runtime",
            "task": "android_local_generate",
            "transport": "lan_8010",
            "node_id": node["node_id"],
            "job": result,
            "response": (result.get("result") or {}).get("response"),
            "truth": "Generacion ejecutada por backend LLM nativo en Android." if completed else "El nodo Android acepto el job pero no completo generacion LLM real.",
        }

    relay = relay_settings()
    if relay.get("admin_token"):
        federation = Federation()
        client = PublicRelayClient(str(relay["url"]), str(relay["admin_token"]), timeout=12)
        sync = client.sync_nodes_to_federation(federation)
        relay_hosts = android_llm_host_nodes(sync.get("nodes", []))
        if request.node_id:
            relay_hosts = [node for node in relay_hosts if str(node.get("node_id")) == request.node_id]
        if relay_hosts:
            node = relay_hosts[0]
            job_id = client.create_job(str(node["node_id"]), task="android_local_generate", payload=payload, seconds=1.0)
            job = client.wait_for_job(job_id, timeout=request.wait_timeout)
            completed = job.get("status") == "completed" and bool((job.get("result") or {}).get("ok"))
            return {
                "status": "ok" if completed else job.get("status", "degraded"),
                "mode": "distributed-runtime",
                "task": "android_local_generate",
                "transport": "public_relay_fallback",
                "node_id": node["node_id"],
                "job": job,
                "response": (job.get("result") or {}).get("response"),
                "truth": "Generacion ejecutada por backend LLM nativo en Android via relay publico." if completed else "El relay encontro host Android, pero la generacion no completo correctamente.",
            }

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No hay host LLM Android real. Ejecuta Doctor Android y prepara la APK con llama-cli ejecutable en bin/ y un modelo .gguf en models/.",
    )


@app.get("/api/semantic/doctor")
def semantic_doctor() -> dict[str, Any]:
    LIFE_PULSE.record_action("semantic_doctor")
    return SemanticEmbeddingEngine().doctor()


@app.get("/api/semantic/governance/doctor")
def semantic_governance_doctor() -> dict[str, Any]:
    LIFE_PULSE.record_action("semantic_governance_doctor")
    return SemanticMemoryGovernance().doctor()


@app.post("/api/semantic/ingest-and-embed")
def semantic_ingest_and_embed(request: SemanticIngestRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return SemanticEmbeddingEngine().ingest_and_embed(content=request.content, domain=request.domain, source_type=request.source_type, source_ref=request.source_ref, metadata=request.metadata, model=clean_model(request.model))


@app.post("/api/semantic/documents/{document_id}/embed")
def semantic_embed_document(document_id: str, request: SemanticEmbedRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return SemanticEmbeddingEngine().embed_document(document_id, model=clean_model(request.model)).to_dict()


@app.post("/api/semantic/documents/{document_id}/transition")
def semantic_transition_document(document_id: str, request: SemanticTransitionRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@app.post("/api/semantic/search")
def semantic_search(request: SemanticSearchRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return SemanticSearchEngine().search(query=request.query, model=clean_model(request.model), limit=request.limit, min_similarity=request.min_similarity, domain=request.domain)


def operational_awareness_context() -> dict[str, Any]:
    qualia = QUALIA.snapshot(refresh_life=False)
    life = LIFE_PULSE.snapshot()
    if int(life.get("counters", {}).get("cycles") or 0) == 0:
        life = LIFE_PULSE.tick()
        qualia = QUALIA.snapshot(refresh_life=False)
    capacity = build_model_capacity(sync_relay=False)
    local = capacity.get("local", {})
    federation = capacity.get("federation", {})
    authorized = federation.get("authorized", {})
    hardware = local.get("hardware", {})
    return {
        "source": "api/system/life + api/system/model-capacity",
        "kind": "living_senses_operational_awareness",
        "qualia": qualia,
        "life": {
            "status": life.get("status"),
            "running": life.get("running"),
            "uptime_seconds": life.get("uptime_seconds"),
            "interval_seconds": life.get("interval_seconds"),
            "counters": life.get("counters", {}),
            "actions": life.get("actions", {}),
            "integrity_ok": (life.get("integrity") or {}).get("ok"),
            "policy": life.get("policy", {}),
        },
        "reflection": life.get("reflection", {}),
        "local": {
            "hardware_tier": hardware.get("tier"),
            "ram_available_gb": hardware.get("ram_available_gb"),
            "gpu_names": [gpu.get("name") for gpu in hardware.get("gpus", []) if isinstance(gpu, dict)],
            "ollama_ok": (local.get("ollama") or {}).get("ok"),
            "ollama_models": (local.get("ollama") or {}).get("models", [])[:10],
            "docker_ok": (local.get("docker") or {}).get("ok"),
        },
        "federation": {
            "runtime": authorized.get("runtime"),
            "runtime_node_count": authorized.get("runtime_node_count", 0),
            "llm_hosts": authorized.get("llm_hosts", 0),
            "ram_authorized_gb": authorized.get("ram_authorized_gb", 0),
            "cpu_authorized_count": authorized.get("cpu_authorized_count", 0),
        },
        "answering_rule": "Si el usuario pregunta por mi estado, pulso, neuronas propuestas o acciones, usar estos datos como estado operativo vivo; aclarar que no son recuerdos semanticos consolidados.",
    }


@app.get("/api/neurons/candidates")
def list_neuron_candidates(limit_runs: int = 50, include_decided: bool = True, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return NeuronCandidateGovernance().list_candidates(limit_runs=limit_runs, include_decided=include_decided)


@app.post("/api/neurons/candidates/approve")
def approve_neuron_candidate(request: NeuronCandidateDecisionRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return NeuronCandidateGovernance().approve(
        run_id=request.run_id,
        name=request.name,
        approved_by=request.decided_by,
        notes=request.notes,
    )


@app.post("/api/neurons/candidates/reject")
def reject_neuron_candidate(request: NeuronCandidateDecisionRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_triade_api_key)
    return NeuronCandidateGovernance().reject(
        run_id=request.run_id,
        name=request.name,
        rejected_by=request.decided_by,
        notes=request.notes,
    )


def run_context_with_living_awareness(base_context: dict[str, Any]) -> dict[str, Any]:
    context = build_run_context_with_pulse(base_context, build_system_pulse)
    context["triade_operational_awareness"] = operational_awareness_context()
    return context


@app.post("/api/run")
@app.post("/triade/run")
def run_triade(request: RunRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    LIFE_PULSE.record_action("run")
    require_key(x_triade_api_key)
    runner = TriadeRunner(
        use_ollama=request.use_ollama,
        hypothalamus_model=clean_model(request.hypothalamus_model),
        central_model=clean_model(request.central_model),
        auto_select_models=request.auto_select_models,
    )
    return runner.run(
        request.text,
        source=request.source,
        context=run_context_with_living_awareness(request.context),
        semantic_recall_enabled=request.semantic_recall_enabled,
        semantic_model=clean_model(request.semantic_model),
        semantic_limit=request.semantic_limit,
        semantic_min_similarity=request.semantic_min_similarity,
        semantic_domain=request.semantic_domain,
        semantic_allow_experimental=request.semantic_allow_experimental,
    )


HTML = """
<!doctype html><html lang='es'><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>
<title>Tríade Ω Single Port</title>
<style>
body{margin:0;background:#080b10;color:#edf2ff;font-family:Inter,system-ui,sans-serif;padding:18px}.app{max-width:1180px;margin:auto;display:grid;grid-template-columns:350px 1fr;gap:16px}.card{background:#121722;border:1px solid #263246;border-radius:20px}.side{padding:18px;overflow:auto;max-height:calc(100vh - 36px)}.main{height:calc(100vh - 36px);display:flex;flex-direction:column}label{display:block;color:#9aa7bd;font-size:12px;margin:12px 0 6px}input,select,textarea{width:100%;box-sizing:border-box;background:#171f2e;color:#edf2ff;border:1px solid #263246;border-radius:12px;padding:10px}button{width:100%;margin-top:10px;border:0;border-radius:12px;padding:11px;font-weight:800;background:linear-gradient(135deg,#73c7ff,#9bffb1);color:#061018}.secondary{background:#223047;color:#edf2ff;border:1px solid #263246}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.chat{flex:1;overflow:auto;padding:16px}.msg{padding:13px;border-radius:16px;margin:10px 0;white-space:pre-wrap}.user{background:#1f6feb;margin-left:12%}.bot{background:#171f2e;border:1px solid #263246;margin-right:12%}.meta{font-size:12px;color:#9aa7bd;margin-top:8px}.composer{display:grid;grid-template-columns:1fr 120px;gap:10px;padding:14px;border-top:1px solid #263246}.box{background:#0d121c;border:1px solid #263246;border-radius:12px;padding:10px;margin-top:10px;font-size:12px;white-space:pre-wrap;max-height:260px;overflow:auto}.top{padding:14px;border-bottom:1px solid #263246;color:#9aa7bd}.ok{color:#9bffb1}.hint{font-size:11px;color:#8292ad;margin-top:4px}@media(max-width:850px){.app{grid-template-columns:1fr}.composer{grid-template-columns:1fr}}
</style></head><body><div class='app'><aside class='card side'>
<h2>Tríade Ω</h2><p style='color:#9aa7bd'>Single Port App: conversación, modelos, Cristal y memoria semántica en 8010.</p>
<label>API key</label><input id='key' type='password'/><div class='row'><div><label>Intención router</label><select id='intent'><option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option></select></div><div><label>Urgencia</label><select id='urgency'><option>medium</option><option>low</option><option>high</option></select></div></div>
<label>Hipotálamo (vacío = automático)</label><input id='hyp' value=''/><label>Central (vacío = automático)</label><input id='cen' value=''/><label><input id='ollama' type='checkbox'/> Usar Ollama</label><label><input id='auto' type='checkbox' checked/> Auto elegir modelos</label>
<hr style='border-color:#263246;margin:16px 0'/><b style='font-size:13px'>Contexto del Cristal</b><div class='hint'>Evita comparar runs de proyectos o neuronas diferentes.</div>
<label>Proyecto (opcional)</label><input id='project' placeholder='triade-local, xiaos, elestial...'/><label>Neurona activa (opcional)</label><input id='neuron' placeholder='cristal, xiaos, bodega...'/><label>Sesión (opcional)</label><input id='session' placeholder='sesion-prueba-01'/><label>Scope</label><select id='scope'><option value=''>Automático</option><option value='source_intent'>Source + intent</option><option value='session'>Sesión</option><option value='project'>Proyecto</option><option value='neuron'>Neurona</option><option value='project_neuron'>Proyecto + neurona</option></select>
<button onclick='save()'>Guardar</button><button class='secondary' onclick='health()'>Health 8010</button><button class='secondary' onclick='capacity()'>Capacidad y nodos</button><button class='secondary' onclick='router()'>Consultar Router</button><button class='secondary' onclick='compat()'>Compatibilidad</button><button class='secondary' onclick='installQueue()'>Cola modelos</button><button class='secondary' onclick='semanticDoctor()'>Memoria semántica</button><button class='secondary' onclick='loadNeuronCandidates()'>Neuronas candidatas</button><button class='secondary' onclick='apply()'>Aplicar recomendados</button><button class='secondary' onclick='clearChat()'>Limpiar</button><div id='box' class='box'>Sin consultar.</div>
</aside><main class='card main'><div class='top'><b>Chat local auditable</b><br><span id='status'>Listo</span></div><section id='chat' class='chat'></section><div class='composer'><textarea id='msg' placeholder='Escribe... Ctrl+Enter' onkeydown='keysend(event)'></textarea><button onclick='send()'>Enviar</button></div></main></div>
<script>
const $=id=>document.getElementById(id);let lastRouter=null;const settings=['key','hyp','cen','intent','urgency','project','neuron','session','scope'];function save(){settings.forEach(k=>localStorage.setItem('triade_sp_'+k,$(k).value));localStorage.setItem('triade_sp_ollama',$('ollama').checked);localStorage.setItem('triade_sp_auto',$('auto').checked);status('Guardado',true)}function load(){settings.forEach(k=>{const v=localStorage.getItem('triade_sp_'+k);if(v!==null)$(k).value=v});$('ollama').checked=localStorage.getItem('triade_sp_ollama')==='true';$('auto').checked=localStorage.getItem('triade_sp_auto')!=='false'}function status(t,ok=false){$('status').textContent=t;$('status').className=ok?'ok':''}function add(cls,text,meta=''){let d=document.createElement('div');d.className='msg '+cls;d.textContent=text;if(meta){let m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}$('chat').appendChild(d);$('chat').scrollTop=$('chat').scrollHeight}function context(){let c={};if($('project').value.trim())c.project_id=$('project').value.trim();if($('neuron').value.trim())c.active_neuron=$('neuron').value.trim();if($('session').value.trim())c.session_id=$('session').value.trim();if($('scope').value)c.context_scope=$('scope').value;return c}
async function health(){try{let r=await fetch('/api/health');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({mode:j.mode,hardware:j.hardware,contexts:j.doctor?.crystal_contexts,ollama:j.ollama?.ok,runs:j.doctor?.counts?.runs},null,2);status('Health OK',true)}catch(e){status('Health falló: '+e.message)}}
async function router(){try{let r=await fetch('/api/router/doctor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intent:$('intent').value,urgency:$('urgency').value})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);lastRouter=j;let d=j.router.decisions;$('box').textContent=JSON.stringify({central:d.central?.selected_model,hypothalamus:d.hypothalamus?.selected_model,fast:d.fast?.selected_model,deep:d.deep?.selected_model},null,2);status('Router OK',true)}catch(e){status('Router falló: '+e.message)}}
async function compat(){try{let r=await fetch('/api/models/compatibility');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.matrix.summary,counts:j.matrix.counts,models:j.matrix.models},null,2);status('Compatibilidad OK',true)}catch(e){status('Compatibilidad falló: '+e.message)}}
async function installQueue(){try{let r=await fetch('/api/models/install-queue?include_allowed=false');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.summary,count:j.count,policy:j.policy,candidates:j.candidates},null,2);status('Cola OK',true)}catch(e){status('Cola falló: '+e.message)}}
async function capacity(){try{let r=await fetch('/api/system/model-capacity?sync_relay=true');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);box.textContent=JSON.stringify({pc:{tier:j.local.hardware.tier,ram_free:j.local.hardware.ram_available_gb,ollama:j.local.ollama.ok,docker:j.local.docker.ok,missing:j.local.missing_for_comfortable_models,counts:j.local.counts},nodos:j.federation.nodes.map(n=>({name:n.name,node_id:n.node_id,online:n.online,native_android:n.native_android,cpu:n.cpu_count,ram_free:n.ram_available_gb,score:n.benchmark_score,use:n.recommended_use,feed:n.can_feed_local_models,host:n.can_host_llm,missing:n.missing_for_comfortable_models})),constantes:j.constants},null,2);status('Capacidad actualizada',true)}catch(e){status('Capacidad falló: '+e.message)}}

async function loadNeuronCandidates(){
  try{
    const r=await fetch(routes.neurons+'?limit_runs=30&include_decided=true',{headers:{'X-TRIADE-API-Key':key()}});
    const j=await r.json();
    if(!r.ok)throw Error(j.detail||j.status);
    renderNeuronCandidates(j.candidates||[]);
    setStatus('Neuronas candidatas cargadas: '+(j.count||0),true);
  }catch(err){
    setStatus('Neuronas candidatas falló: '+err.message,false);
  }
}
function escapeHtml(s){
  return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
}
function renderNeuronCandidates(items){
  const box=document.getElementById('box');
  if(!box)return;
  if(!items.length){
    box.innerHTML='No hay neuronas candidatas.';
    return;
  }
  let html='<b>Neuronas candidatas</b><br><span class="hint">Candidate → aprobación humana → experimental. No se consolida como stable automáticamente.</span>';
  html+=items.slice(0,30).map(c=>{
    const decision=c.decision;
    const decisionHtml=decision?`<div class="hint">Decisión: <b>${escapeHtml(decision.decision)}</b> · siguiente: ${escapeHtml(decision.next_status)} · por: ${escapeHtml(decision.decided_by)}</div>`:'';
    const buttons=decision?'':`
      <div class="row">
        <button onclick="approveCandidate('${escapeHtml(c.run_id)}','${escapeHtml(c.name)}')">Aprobar</button>
        <button class="secondary" onclick="rejectCandidate('${escapeHtml(c.run_id)}','${escapeHtml(c.name)}')">Rechazar</button>
      </div>`;
    return `<div class="box" style="max-height:none">
      <b>${escapeHtml(c.display_name||c.name)}</b>
      <div class="hint">${escapeHtml(c.name)} · ${escapeHtml(c.severity)} · ${escapeHtml(c.source)} · ${escapeHtml(c.run_id)}</div>
      <p>${escapeHtml(c.mission)}</p>
      ${decisionHtml}
      ${buttons}
    </div>`;
  }).join('');
  box.innerHTML=html;
}
async function approveCandidate(runId,name){
  await decideCandidate(routes.neuronsApprove,runId,name,'Aprobada desde UI para pasar a experimental.');
}
async function rejectCandidate(runId,name){
  await decideCandidate(routes.neuronsReject,runId,name,'Rechazada desde UI.');
}
async function decideCandidate(url,runId,name,notes){
  try{
    const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':key()},body:JSON.stringify({run_id:runId,name:name,decided_by:'Santiago',notes})});
    const j=await r.json();
    if(!r.ok||j.status==='error')throw Error(j.detail||j.error||r.status);
    setStatus('Decisión registrada: '+name,true);
    await loadNeuronCandidates();
  }catch(err){
    setStatus('Decisión falló: '+err.message,false);
  }
}
async function semanticDoctor(){try{let r=await fetch('/api/semantic/governance/doctor');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify(j,null,2);status('Gobierno semántico consultado',true)}catch(e){status('Memoria semántica falló: '+e.message)}}

async function loadNeuronCandidates(){
  try{
    let r=await fetch('/api/neurons/candidates?limit_runs=20&include_decided=true',{headers:{'X-TRIADE-API-Key':$('key').value}});
    let j=await r.json();
    if(!r.ok)throw Error(j.detail||r.status);
    renderNeuronCandidates(j.candidates||[]);
    status('Neuronas candidatas cargadas: '+(j.count||0),true)
  }catch(e){
    status('Neuronas candidatas falló: '+e.message)
  }
}
function esc(s){
  return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))
}
function renderNeuronCandidates(items){
  if(!items.length){$('box').innerHTML='No hay neuronas candidatas.';return}
  let html='<b>Neuronas candidatas</b><br><span class="hint">Candidate → aprobación humana → experimental. No se consolida como stable automáticamente.</span>';
  html+=items.slice(0,30).map(c=>{
    let decided=c.decision;
    let decision=decided?`<div class="hint">Decisión: <b>${esc(decided.decision)}</b> · siguiente: ${esc(decided.next_status)} · por: ${esc(decided.decided_by)}</div>`:'';
    let buttons=decided?'':`
      <div class="row">
        <button onclick="approveCandidate('${esc(c.run_id)}','${esc(c.name)}')">Aprobar</button>
        <button class="secondary" onclick="rejectCandidate('${esc(c.run_id)}','${esc(c.name)}')">Rechazar</button>
      </div>`;
    return `<div class="box" style="max-height:none">
      <b>${esc(c.display_name||c.name)}</b>
      <div class="hint">${esc(c.name)} · ${esc(c.severity)} · ${esc(c.source)} · ${esc(c.run_id)}</div>
      <p>${esc(c.mission)}</p>
      ${decision}
      ${buttons}
    </div>`
  }).join('');
  $('box').innerHTML=html;
}
async function approveCandidate(runId,name){
  await decideCandidate('/api/neurons/candidates/approve',runId,name,'Aprobada desde UI para pasar a experimental.');
}
async function rejectCandidate(runId,name){
  await decideCandidate('/api/neurons/candidates/reject',runId,name,'Rechazada desde UI.');
}
async function decideCandidate(url,runId,name,notes){
  try{
    let r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':$('key').value},body:JSON.stringify({run_id:runId,name:name,decided_by:'Santiago',notes:notes})});
    let j=await r.json();
    if(!r.ok||j.status==='error')throw Error(j.detail||j.error||r.status);
    status('Decisión registrada: '+name,true);
    await loadNeuronCandidates();
  }catch(e){
    status('Decisión falló: '+e.message)
  }
}
function apply(){if(!lastRouter){status('Consulta router primero');return}let d=lastRouter.router.decisions;if(d.hypothalamus?.selected_model)$('hyp').value=d.hypothalamus.selected_model;if(d.central?.selected_model)$('cen').value=d.central.selected_model;$('ollama').checked=true;$('auto').checked=false;save();status('Recomendados aplicados manualmente',true)}
async function send(){save();let text=$('msg').value.trim();if(!text)return;$('msg').value='';add('user',text);status('Procesando...');try{let r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':$('key').value},body:JSON.stringify({text,source:'single-port-ui',use_ollama:$('ollama').checked,hypothalamus_model:$('hyp').value,central_model:$('cen').value,auto_select_models:$('auto').checked,context:context()})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);let t=j.crystal_temporal_state||{};add('bot',j.response,[j.run_id,'Q '+t.status,'scope '+t.context_scope,'ctx '+t.context_key,'H '+j.models?.hypothalamus?.name,'C '+j.models?.central?.name].filter(Boolean).join(' · '));status('Respuesta recibida',true)}catch(e){add('bot','Error: '+e.message);status('Error')}}function clearChat(){$('chat').innerHTML=''}function keysend(e){if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))send()}load();add('bot','Tríade Ω lista. La memoria semántica autorizada requiere estado stable o autorización experimental explícita.');
</script></body></html>
"""


TRIADE_UI_HTML = """
<!doctype html><html lang='es'><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>
<title>Tríade Ω Single Port</title>
<style>
:root{color-scheme:dark;--bg:#080b10;--panel:#111720;--line:#263244;--text:#eef4ff;--muted:#9aa7bd;--ok:#8ef0a4;--warn:#ffd166;--bad:#ff7b7b;--blue:#76c7ff}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif}.shell{height:100vh;display:grid;grid-template-columns:300px minmax(360px,1fr) 360px}.rail,.pulse{border-color:var(--line);background:var(--panel);overflow:auto}.rail{border-right:1px solid var(--line);padding:18px}.pulse{border-left:1px solid var(--line);padding:16px}.main{display:flex;flex-direction:column;min-width:0}.brand{display:flex;align-items:center;justify-content:space-between;gap:10px}.brand h1{font-size:22px;margin:0}.state-dot{width:11px;height:11px;border-radius:50%;background:var(--warn);box-shadow:0 0 16px currentColor}.state-dot.ok{background:var(--ok)}.muted,.hint{color:var(--muted)}.hint{font-size:12px;margin-top:6px}.section{border-top:1px solid var(--line);margin-top:16px;padding-top:14px}.section h2,.pulse h2{font-size:13px;margin:0 0 10px;color:#cbd7ea;text-transform:uppercase;letter-spacing:.08em}label{display:block;color:var(--muted);font-size:12px;margin:10px 0 6px}input,select,textarea{width:100%;background:#171f2b;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:10px}textarea{resize:vertical;min-height:58px}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.toggle{display:flex;align-items:center;gap:8px;color:#cbd7ea;font-size:13px;margin-top:10px}.toggle input{width:auto}button{width:100%;border:0;border-radius:8px;padding:10px 11px;font-weight:800;background:#7dd7ff;color:#061018;margin-top:8px}.secondary{background:#202b3b;color:var(--text);border:1px solid var(--line)}.ghost{background:transparent;color:var(--text);border:1px solid var(--line)}details{border:1px solid var(--line);border-radius:8px;padding:10px;margin-top:10px;background:#0c1119}summary{cursor:pointer;color:#d8e4f8;font-weight:700}.top{border-bottom:1px solid var(--line);padding:14px 18px;display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center}.organs{display:flex;gap:8px;flex-wrap:wrap}.organ{border:1px solid var(--line);border-radius:999px;padding:6px 9px;background:#121a26;color:#cbd7ea;font-size:12px}.organ.ok{border-color:#2d7f50;color:var(--ok)}.chat{flex:1;overflow:auto;padding:18px}.msg{padding:13px;border-radius:8px;margin:10px 0;white-space:pre-wrap;line-height:1.45}.user{background:#1d5fc0;margin-left:14%}.bot{background:#151d29;border:1px solid var(--line);margin-right:14%}.meta{font-size:12px;color:var(--muted);margin-top:8px}.composer{display:grid;grid-template-columns:1fr 112px;gap:10px;padding:14px;border-top:1px solid var(--line)}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric{border:1px solid var(--line);border-radius:8px;padding:10px;background:#0d131d}.metric b{display:block;font-size:20px}.metric span{color:var(--muted);font-size:12px}.oktxt{color:var(--ok)}.warntxt{color:var(--warn)}.badtxt{color:var(--bad)}.node{border:1px solid var(--line);border-radius:8px;padding:10px;background:#0d131d;margin:8px 0}.node-head{display:flex;justify-content:space-between;gap:8px}.tag{border-radius:999px;padding:3px 7px;background:#1d2938;color:#cbd7ea;font-size:11px}.feed{color:var(--ok)}.host{color:var(--blue)}.box{background:#090e15;border:1px solid var(--line);border-radius:8px;padding:10px;margin-top:10px;font-size:12px;white-space:pre-wrap;max-height:240px;overflow:auto}.empty{color:var(--muted);font-size:13px}.live-line{font-size:12px;color:var(--muted);margin-top:8px}.critical{border-color:#68404a;background:#1a1116}.ready{border-color:#315f43}.model-list{display:flex;flex-wrap:wrap;gap:6px}.pill{border:1px solid var(--line);border-radius:999px;padding:4px 8px;font-size:12px;color:#d8e4f8}@media(max-width:1050px){.shell{height:auto;grid-template-columns:1fr}.rail,.pulse{border:0;border-bottom:1px solid var(--line)}.main{min-height:70vh}.composer{grid-template-columns:1fr}.user,.bot{margin-left:0;margin-right:0}}
</style></head><body><div class='shell'>
<aside class='rail'><div class='brand'><h1>Tríade Ω</h1><span id='liveDot' class='state-dot'></span></div><div class='hint'>8010 local: conversación, memoria, modelos y federación.</div>
<div class='section'><h2>Modo</h2><label>API key</label><input id='key' type='password'/><div class='row'><div><label>Intención</label><select id='intent'><option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option></select></div><div><label>Urgencia</label><select id='urgency'><option>medium</option><option>low</option><option>high</option></select></div></div><label class='toggle'><input id='ollama' type='checkbox'/> Usar Ollama</label><label class='toggle'><input id='auto' type='checkbox' checked/> Auto elegir modelos</label><button onclick='save()'>Guardar estado</button></div>
<div class='section'><h2>Cristal</h2><label>Proyecto</label><input id='project' placeholder='triade-local'/><label>Neurona activa</label><input id='neuron' placeholder='cristal, bodega...'/><details><summary>Contexto especial</summary><label>Sesión</label><input id='session' placeholder='sesion-prueba-01'/><label>Scope</label><select id='scope'><option value=''>Automático</option><option value='source_intent'>Source + intent</option><option value='session'>Sesión</option><option value='project'>Proyecto</option><option value='neuron'>Neurona</option><option value='project_neuron'>Proyecto + neurona</option></select><label>Hipotálamo</label><input id='hyp' value=''/><label>Central</label><input id='cen' value=''/></details></div>
<div class='section'><h2>Acciones</h2><button onclick='capacity(true)'>Actualizar pulso</button><button class='secondary' onclick='androidModelDoctor()'>Doctor modelos Android</button><button class='secondary' onclick='runtimeProbe()'>Probar runtime distribuido</button><button class='secondary' onclick='runtimePreprocess()'>Preprocesar en nodos</button><button class='secondary' onclick='router()'>Recomendar modelos</button><a href='/downloads/triade-android-node.apk'><button class='secondary' type='button'>Descargar Android Node</button></a><details><summary>Herramientas ocasionales</summary><button class='secondary' onclick='health()'>Health completo</button><button class='secondary' onclick='compat()'>Compatibilidad</button><button class='secondary' onclick='installQueue()'>Cola modelos</button><button class='secondary' onclick='semanticDoctor()'>Memoria semántica</button><button class='secondary' onclick='loadNeuronCandidates()'>Neuronas candidatas</button><button class='ghost' onclick='apply()'>Aplicar recomendados</button><button class='ghost' onclick='clearChat()'>Limpiar chat</button></details><div id='box' class='box'>Pulso inicial pendiente.</div></div></aside>
<main class='main'><div class='top'><div><b>Chat local auditable</b><br><span id='status' class='muted'>Iniciando pulso...</span></div><div class='organs'><span id='orgCentral' class='organ'>Central</span><span id='orgHyp' class='organ'>Hipotálamo</span><span id='orgMem' class='organ'>Bodega</span><span id='orgFed' class='organ'>Federación</span></div></div><section id='chat' class='chat'></section><div class='composer'><textarea id='msg' placeholder='Escribe... Ctrl+Enter' onkeydown='keysend(event)'></textarea><button onclick='send()'>Enviar</button></div></main>
<aside class='pulse'><h2>Pulso vivo</h2><div id='summary' class='grid2'><div class='metric'><b>...</b><span>PC</span></div><div class='metric'><b>...</b><span>Nodos</span></div></div><div id='missing' class='section'></div><div class='section'><h2>Modelos</h2><div id='models' class='model-list'><span class='empty'>Sin lectura todavía.</span></div></div><div class='section'><h2>Nodos que alimentan</h2><div id='nodes'><span class='empty'>Sin nodos sincronizados.</span></div></div><div class='live-line' id='liveLine'>Sincronización cada 15 s.</div></aside>
</div><script>
const $=id=>document.getElementById(id);let lastRouter=null,lastCapacity=null;const settings=['key','hyp','cen','intent','urgency','project','neuron','session','scope'];function save(){settings.forEach(k=>localStorage.setItem('triade_sp_'+k,$(k).value));localStorage.setItem('triade_sp_ollama',$('ollama').checked);localStorage.setItem('triade_sp_auto',$('auto').checked);status('Estado guardado',true)}function load(){settings.forEach(k=>{const v=localStorage.getItem('triade_sp_'+k);if(v!==null)$(k).value=v});$('ollama').checked=localStorage.getItem('triade_sp_ollama')==='true';$('auto').checked=localStorage.getItem('triade_sp_auto')!=='false'}function status(t,ok=false){$('status').textContent=t;$('status').className=ok?'oktxt':'muted'}function add(cls,text,meta=''){let d=document.createElement('div');d.className='msg '+cls;d.textContent=text;if(meta){let m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}$('chat').appendChild(d);$('chat').scrollTop=$('chat').scrollHeight}function context(){let c={};if($('project').value.trim())c.project_id=$('project').value.trim();if($('neuron').value.trim())c.active_neuron=$('neuron').value.trim();if($('session').value.trim())c.session_id=$('session').value.trim();if($('scope').value)c.context_scope=$('scope').value;return c}
function fmt(n){return Number.isFinite(Number(n))?Number(n).toFixed(1):'--'}function cls(ok){return ok?'oktxt':'badtxt'}function setOrgan(id,on){$(id).className='organ '+(on?'ok':'')}function briefMissing(items){return (items||[]).slice(0,4).map(x=>`<div class='metric critical'><b>Falta</b><span>${x}</span></div>`).join('')||`<div class='metric ready'><b>Listo</b><span>Sin bloqueos principales.</span></div>`}
function renderCapacity(j){lastCapacity=j;let h=j.local.hardware, f=j.federation, feeders=f.online_feeders||[], hosts=f.llm_hosts||[], a=f.authorized||{};$('liveDot').className='state-dot ok';setOrgan('orgCentral',j.local.ollama.ok);setOrgan('orgHyp',j.local.ollama.ok);setOrgan('orgMem',true);setOrgan('orgFed',feeders.length>0);$('summary').innerHTML=`<div class='metric ${h.tier==='low'?'critical':'ready'}'><b>${h.tier}</b><span>PC local · ${fmt(h.ram_available_gb)} GB RAM libre</span></div><div class='metric ${feeders.length?'ready':'critical'}'><b>${feeders.length}</b><span>dispositivos federados · ${hosts.length} hosts LLM</span></div><div class='metric ${feeders.length?'ready':'critical'}'><b>${a.cpu_authorized_count||0}</b><span>CPU autorizada federada</span></div><div class='metric ${a.ram_authorized_gb>=4?'ready':'critical'}'><b>${fmt(a.ram_authorized_gb)}</b><span>GB RAM federada por suma</span></div><div class='metric ${a.gpu_node_count?'ready':'critical'}'><b>${fmt(a.vram_authorized_gb)}</b><span>GB VRAM/GPU federada</span></div><div class='metric ${a.active_job_runtime?'ready':'critical'}'><b>${a.active_job_runtime?'activo':'pendiente'}</b><span>runtime por jobs · LLM único aún pendiente</span></div><div class='metric'><b class='${cls(j.local.ollama.ok)}'>${j.local.ollama.ok?'activo':'apagado'}</b><span>Ollama</span></div><div class='metric'><b class='${cls(j.local.docker.ok)}'>${j.local.docker.ok?'listo':'pendiente'}</b><span>Docker</span></div>`;$('missing').innerHTML=`<h2>Qué falta</h2>${briefMissing([...(j.local.missing_for_comfortable_models||[]),...(a.missing_for_real_distributed_models||[])])}`;$('models').innerHTML=(a.runnable_by_aggregate_ram||[]).map(m=>`<span class='pill oktxt'>${m.model} por suma</span>`).join('')||[...(j.local.recommended_models||[]).map(m=>`<span class='pill oktxt'>${m.model}</span>`),...(j.local.allowed_models||[]).map(m=>`<span class='pill'>${m.model}</span>`)].join('')||'<span class="empty">No hay modelos que quepan por RAM federada autorizada.</span>';$('nodes').innerHTML=feeders.map(n=>{let source=n.resource_limit_reported?'reportado por app':'asumido: relay no envio porcentaje';let tasks=(n.capabilities?.allowed_tasks||[]).join(', ');return `<div class='node ready'><div class='node-head'><b>${n.name||n.node_id}</b><span class='tag'>${n.resource_limit_percent||0}% ${n.resource_limit_reported?'autorizado':'asumido'}</span></div><div class='hint'>CPU ${n.cpu_authorized_count}/${n.cpu_count} · RAM ${fmt(n.ram_authorized_gb)}/${fmt(n.ram_available_gb)} GB · score ${n.benchmark_score||0}</div><div class='hint'>app ${n.capabilities?.app_version||'?'} · ${source} · ${n.capabilities?.source||'local'}</div><div class='hint'><span class='feed'>jobs: ${tasks||'heartbeat'}</span> · <span class='host'>${n.can_host_llm?'hospeda LLM':'no hospeda LLM'}</span></div></div>`}).join('')||'<span class="empty">Ningún dispositivo federado autorizado online.</span>';$('box').textContent=`PC local ${h.tier}: ${fmt(h.ram_available_gb)} GB libres. Federación: ${a.cpu_authorized_count||0} CPU, ${fmt(a.ram_authorized_gb)} GB RAM y ${fmt(a.vram_authorized_gb)} GB VRAM. Modelos por suma: ${(a.runnable_by_aggregate_ram||[]).length}. Runtime: ${a.runtime}.`;let now=new Date().toLocaleTimeString();$('liveLine').textContent=`Último pulso ${now} · relay ${f.relay?.has_admin_token?'sincronizado':'sin token admin'} · runtime nodes ${a.runtime_node_count||0} · browser no cuenta como nodo`;status('Pulso actualizado',true)}
async function capacity(manual=false){try{let r=await fetch('/api/system/model-capacity?sync_relay=true');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);renderCapacity(j);if(manual)add('bot','Pulso vivo actualizado: revisé PC, modelos, nodos y constantes.')}catch(e){$('liveDot').className='state-dot';status('Pulso falló: '+e.message);$('box').textContent='Error de pulso: '+e.message}}
async function health(){try{let r=await fetch('/api/health');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({mode:j.mode,hardware:j.hardware,contexts:j.doctor?.crystal_contexts,ollama:j.ollama?.ok,runs:j.doctor?.counts?.runs},null,2);status('Health OK',true)}catch(e){status('Health falló: '+e.message)}}async function router(){try{let r=await fetch('/api/router/doctor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intent:$('intent').value,urgency:$('urgency').value})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);lastRouter=j;let d=j.router.decisions;$('box').textContent=JSON.stringify({central:d.central?.selected_model,hypothalamus:d.hypothalamus?.selected_model,fast:d.fast?.selected_model,deep:d.deep?.selected_model},null,2);status('Router OK',true)}catch(e){status('Router falló: '+e.message)}}async function compat(){try{let r=await fetch('/api/models/compatibility');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.matrix.summary,counts:j.matrix.counts,models:j.matrix.models},null,2);status('Compatibilidad OK',true)}catch(e){status('Compatibilidad falló: '+e.message)}}async function installQueue(){try{let r=await fetch('/api/models/install-queue?include_allowed=false');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.summary,count:j.count,policy:j.policy,candidates:j.candidates},null,2);status('Cola OK',true)}catch(e){status('Cola falló: '+e.message)}}async function semanticDoctor(){try{let r=await fetch('/api/semantic/governance/doctor');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify(j,null,2);status('Gobierno semántico consultado',true)}catch(e){status('Memoria semántica falló: '+e.message)}}function apply(){if(!lastRouter){status('Consulta router primero');return}let d=lastRouter.router.decisions;if(d.hypothalamus?.selected_model)$('hyp').value=d.hypothalamus.selected_model;if(d.central?.selected_model)$('cen').value=d.central.selected_model;$('ollama').checked=true;$('auto').checked=false;save();status('Recomendados aplicados',true)}
async function runtimeProbe(){let prompt=$('msg').value.trim()||'Pulso de inferencia distribuida Tríade';status('Enviando señal a nodos...');try{let r=await fetch('/api/distributed-runtime/probe',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt,iterations:250000,wait_timeout:35})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({status:j.status,submitted:j.submitted,completed:j.completed,total_ops:j.total_ops,truth:j.truth},null,2);add('bot',`Runtime distribuido: ${j.completed}/${j.submitted} nodos respondieron · ops ${j.total_ops||0}`);capacity(false)}catch(e){$('box').textContent='Runtime falló: '+e.message;status('Runtime falló: '+e.message)}}
async function androidModelDoctor(){status('Consultando modelos Android...');try{let r=await fetch('/api/distributed-runtime/android-model-doctor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({wait_timeout:35})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({transport:j.transport,completed:j.completed,can_host_llm_count:j.can_host_llm_count,doctors:j.doctors,truth:j.truth},null,2);add('bot',`Doctor Android: ${j.completed} nodos respondieron · hosts LLM reales ${j.can_host_llm_count}.`);capacity(false)}catch(e){$('box').textContent='Doctor Android falló: '+e.message;status('Doctor Android falló: '+e.message)}}
async function runtimePreprocess(){let text=$('msg').value.trim()||'Tríade necesita preparar contexto local con CPU de dispositivos federados autorizados.';status('Preprocesando en nodos...');try{let r=await fetch('/api/distributed-runtime/preprocess',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,max_chunk_chars:1200,wait_timeout:35})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({status:j.status,submitted:j.submitted,completed:j.completed,nodes_used:j.nodes_used,model_feed:j.model_feed},null,2);add('bot',`Preproceso federado listo: ${j.model_feed.word_count||0} palabras, ${j.model_feed.approx_tokens||0} tokens aprox, ${j.completed}/${j.submitted} nodos.`);capacity(false)}catch(e){$('box').textContent='Preproceso falló: '+e.message;status('Preproceso falló: '+e.message)}}
async function send(){save();let text=$('msg').value.trim();if(!text)return;$('msg').value='';add('user',text);status('Procesando...');try{let r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':$('key').value},body:JSON.stringify({text,source:'single-port-ui',use_ollama:$('ollama').checked,hypothalamus_model:$('hyp').value,central_model:$('cen').value,auto_select_models:$('auto').checked,context:context()})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);let t=j.crystal_temporal_state||{};add('bot',j.response,[j.run_id,'Q '+t.status,'scope '+t.context_scope,'ctx '+t.context_key,'H '+j.models?.hypothalamus?.name,'C '+j.models?.central?.name].filter(Boolean).join(' · '));status('Respuesta recibida',true);capacity(false)}catch(e){add('bot','Error: '+e.message);status('Error')}}function clearChat(){$('chat').innerHTML=''}function keysend(e){if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))send()}load();add('bot','Tríade Ω lista. Mantengo pulso vivo de PC, modelos y nodos.');capacity(false);setInterval(()=>capacity(false),15000);
</script></body></html>
"""


TRIADE_REACT_UI_HTML = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Tríade Ω Single Port</title>
  <!-- TrÃ­ade Î© Single Port -->
  <style>
    :root{color-scheme:dark;--bg:#090a0d;--panel:#14161b;--panel2:#101217;--line:#2b3038;--text:#eef1f5;--muted:#9aa3b2;--ok:#78d68f;--warn:#f5c15d;--bad:#ef7f7f;--accent:#7cc7e8}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,system-ui,sans-serif}.app{min-height:100vh;display:grid;grid-template-columns:320px minmax(420px,1fr) 360px}.panel{background:var(--panel);border-color:var(--line);overflow:auto}.left{border-right:1px solid var(--line);padding:16px}.right{border-left:1px solid var(--line);padding:16px}.main{display:flex;flex-direction:column;min-width:0;background:#0b0d11}.brand{display:flex;align-items:center;justify-content:space-between;gap:10px}.brand h1{font-size:22px;margin:0}.small{font-size:12px;color:var(--muted);line-height:1.35}.section{border-top:1px solid var(--line);margin-top:16px;padding-top:14px}.section h2{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#c9d2df;margin:0 0 10px}label{display:block;font-size:12px;color:var(--muted);margin:10px 0 6px}input,select,textarea{width:100%;background:#191c23;color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px}textarea{min-height:58px;resize:vertical}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.toggle{display:flex;align-items:center;gap:8px;color:#d5dbe5}.toggle input{width:auto}button,.btn{display:inline-flex;align-items:center;justify-content:center;width:100%;min-height:38px;border:0;border-radius:8px;padding:9px 10px;font-weight:800;background:var(--accent);color:#061018;text-decoration:none;margin-top:8px;cursor:pointer}.secondary{background:#222733;color:var(--text);border:1px solid var(--line)}.ghost{background:transparent;color:var(--text);border:1px solid var(--line)}details{border:1px solid var(--line);border-radius:8px;background:#10131a;margin-top:10px;padding:10px}summary{cursor:pointer;font-weight:800}.alert{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line);background:#11141a}.dot{width:12px;height:12px;border-radius:99px;background:var(--warn);box-shadow:0 0 16px currentColor}.dot.ok{background:var(--ok)}.dot.bad{background:var(--bad)}.status{font-weight:900}.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.organs{display:flex;gap:8px;flex-wrap:wrap}.organ{border:1px solid var(--line);border-radius:999px;padding:5px 8px;font-size:12px;color:#cbd4df}.organ.on{border-color:#3f8755;color:var(--ok)}.chat{flex:1;overflow:auto;padding:18px}.msg{padding:12px;border-radius:8px;margin:10px 0;white-space:pre-wrap;line-height:1.45}.user{background:#244f8f;margin-left:14%}.bot{background:#151922;border:1px solid var(--line);margin-right:14%}.meta{font-size:12px;color:var(--muted);margin-top:8px}.composer{display:grid;grid-template-columns:1fr 110px;gap:10px;padding:14px;border-top:1px solid var(--line)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric,.node,.box{border:1px solid var(--line);border-radius:8px;background:var(--panel2);padding:10px}.metric b{display:block;font-size:20px}.metric span{font-size:12px;color:var(--muted)}.ready{border-color:#365c43}.critical{border-color:#704148}.node{margin:8px 0}.node-head{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.tag{border-radius:999px;background:#252b36;color:#d8dee8;padding:3px 7px;font-size:11px;white-space:nowrap}.box{white-space:pre-wrap;max-height:260px;overflow:auto;font-size:12px;color:#d8dee8}.pill{display:inline-flex;border:1px solid var(--line);border-radius:999px;padding:4px 8px;margin:3px;font-size:12px}.live{font-size:12px;color:var(--muted);margin-top:8px}.empty{color:var(--muted);font-size:13px}@media(max-width:1120px){.app{grid-template-columns:1fr}.left,.right{border:0;border-bottom:1px solid var(--line)}.main{min-height:70vh}.composer{grid-template-columns:1fr}.user,.bot{margin-left:0;margin-right:0}}
  </style>
</head>
<body>
  <div id="root" data-routes="/api/run /api/system/pulse /api/system/life /api/system/qualia /api/system/model-capacity">
    <main class="app">
      <aside class="panel left"><h1>Tríade Ω</h1><p class="small">Pulso vivo · Herramientas ocasionales · /downloads/triade-android-node.apk</p></aside>
      <section class="main"><div class="alert"><span class="dot"></span><b>Iniciando tablero React...</b><span class="small">8010</span></div></section>
      <aside class="panel right"><h2>Pulso vivo</h2></aside>
    </main>
  </div>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script>
    const e = React.createElement;
    const routes = {
      pulse: '/api/system/pulse?sync_relay=true',
      capacity: '/api/system/model-capacity?sync_relay=true',
      lease: '/api/federation/resource-lease?sync_relay=true',
      run: '/api/run',
      router: '/api/router/doctor',
      health: '/api/health',
      compat: '/api/models/compatibility',
      queue: '/api/models/install-queue?include_allowed=false',
      semantic: '/api/semantic/governance/doctor',
      qualia: '/api/system/qualia',
      neurons: '/api/neurons/candidates',
      neuronsApprove: '/api/neurons/candidates/approve',
      neuronsReject: '/api/neurons/candidates/reject',
      androidDoctor: '/api/distributed-runtime/android-model-doctor',
      androidGenerate: '/api/distributed-runtime/android-local-generate',
      preprocess: '/api/distributed-runtime/preprocess',
      probe: '/api/distributed-runtime/probe'
    };

    function n(value, fallback='--') {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(1) : fallback;
    }

    function PanelMetric({label, value, tone, hint}) {
      return e('div', {className: 'metric ' + (tone || '')}, e('b', null, value), e('span', null, label), hint ? e('div', {className: 'small'}, hint) : null);
    }

    function App() {
      const [pulse, setPulse] = React.useState(null);
      const [cap, setCap] = React.useState(null);
      const [lease, setLease] = React.useState(null);
      const [log, setLog] = React.useState('Pulso inicial pendiente.');
      const [chat, setChat] = React.useState([{who:'bot', text:'Tríade Ω lista. Mantengo pulso vivo de PC, modelos y nodos.'}]);
      const [form, setForm] = React.useState({text:'', key: localStorage.triade_key || '', ollama: localStorage.triade_ollama === 'true', auto: localStorage.triade_auto !== 'false', intent:'conversation', urgency:'medium'});
      const [busy, setBusy] = React.useState(false);

      async function json(url, options) {
        const response = await fetch(url, options);
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail || response.status);
        return body;
      }

      async function refresh(manual=false) {
        try {
          const pulseUrl = routes.pulse + '&intent=' + encodeURIComponent(form.intent) + '&urgency=' + encodeURIComponent(form.urgency);
          const [systemPulse, resourceLease] = await Promise.all([json(pulseUrl), json(routes.lease)]);
          setPulse(systemPulse);
          setCap(systemPulse.capacity);
          setLease(resourceLease);
          setLog(JSON.stringify({summary: systemPulse.summary, alerts: systemPulse.alerts, truth: systemPulse.truth}, null, 2));
          if (manual) append('bot', 'Pulso vivo actualizado: revisé PC, Docker, Ollama, nodos Android y runtime.');
        } catch (err) {
          setLog('Pulso falló: ' + err.message);
        }
      }

      React.useEffect(() => {
        refresh(false);
        const id = setInterval(() => refresh(false), 15000);
        return () => clearInterval(id);
      }, []);

      function setField(field, value) {
        const next = {...form, [field]: value};
        setForm(next);
        if (field === 'key') localStorage.triade_key = value;
        if (field === 'ollama') localStorage.triade_ollama = String(value);
        if (field === 'auto') localStorage.triade_auto = String(value);
      }

      function append(who, text, meta='') {
        setChat(current => [...current, {who, text, meta}]);
      }

      async function action(name, fn) {
        setBusy(true);
        try {
          const result = await fn();
          setLog(JSON.stringify(result, null, 2));
          await refresh(false);
        } catch (err) {
          setLog(name + ' falló: ' + err.message);
        } finally {
          setBusy(false);
        }
      }

      async function send() {
        const text = form.text.trim();
        if (!text) return;
        setField('text', '');
        append('user', text);
        await action('Chat', async () => {
          const result = await json(routes.run, {
            method:'POST',
            headers:{'Content-Type':'application/json','X-TRIADE-API-Key':form.key},
            body: JSON.stringify({text, source:'single-port-react-ui', use_ollama:form.ollama, auto_select_models:form.auto})
          });
          append('bot', result.response || JSON.stringify(result), [result.run_id, result.models?.hypothalamus?.name, result.models?.central?.name].filter(Boolean).join(' · '));
          return {run_id: result.run_id, models: result.models, crystal_temporal_state: result.crystal_temporal_state};
        });
      }

      const local = cap?.local || {};
      const hardware = local.hardware || {};
      const federation = cap?.federation || {};
      const authorized = federation.authorized || {};
      const totals = lease?.totals || {};
      const nodes = federation.online_feeders || lease?.devices || [];
      const alerts = pulse?.alerts || [];
      const life = pulse?.life || {};
      const qualia = pulse?.qualia || {};
      const semanticAlignment = qualia.semantic_alignment || {};
      const lifeCounters = life.counters || {};
      const lifeActions = life.actions || {};
      const lifeIntegrity = life.integrity || {};
      const lifeReflection = life.reflection || {};
      const issues = alerts.map(item => item.summary);
      const level = pulse?.level || (issues.length === 0 ? 'ok' : 'warn');
      const alertText = pulse?.summary || (level === 'ok' ? 'Todo activo' : level === 'warn' ? 'Activo con pendientes' : 'Degradado');
      const runnable = authorized.runnable_by_aggregate_ram || [];

      return e('main', {className:'app'},
        e('aside', {className:'panel left'},
          e('div', {className:'brand'}, e('h1', null, 'Tríade Ω'), e('span', {className:'tag'}, '8010')),
          e('p', {className:'small'}, 'Single Port: conversación, doctor, router, modelos, memoria y federación real en un solo pulso.'),
          e('div', {className:'section'}, e('h2', null, 'Modo'),
            e('label', null, 'API key'), e('input', {type:'password', value:form.key, onChange:ev=>setField('key', ev.target.value)}),
            e('div', {className:'row'},
              e('div', null, e('label', null, 'Intención'), e('select', {value:form.intent, onChange:ev=>setField('intent', ev.target.value)}, ['conversation','analyze','memory','build_or_update'].map(x=>e('option', {key:x}, x)))),
              e('div', null, e('label', null, 'Urgencia'), e('select', {value:form.urgency, onChange:ev=>setField('urgency', ev.target.value)}, ['medium','low','high'].map(x=>e('option', {key:x}, x))))
            ),
            e('label', {className:'toggle'}, e('input', {type:'checkbox', checked:form.ollama, onChange:ev=>setField('ollama', ev.target.checked)}), 'Usar Ollama'),
            e('label', {className:'toggle'}, e('input', {type:'checkbox', checked:form.auto, onChange:ev=>setField('auto', ev.target.checked)}), 'Auto elegir modelos')
          ),
          e('div', {className:'section'}, e('h2', null, 'Acciones 24/7'),
            e('button', {onClick:()=>refresh(true), disabled:busy}, 'Actualizar pulso'),
            e('button', {className:'secondary', onClick:()=>action('Doctor Android', () => json(routes.androidDoctor, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({wait_timeout:35})}))}, 'Doctor Android'),
            e('button', {className:'secondary', onClick:()=>action('LLM Android', () => json(routes.androidGenerate, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({prompt:form.text || 'Responde desde el backend LLM Android de Tríade.', max_tokens:128, wait_timeout:90})}))}, 'Generar en Android'),
            e('button', {className:'secondary', onClick:()=>action('Runtime probe', () => json(routes.probe, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({prompt:form.text || 'Pulso distribuido Tríade', iterations:250000, wait_timeout:35})}))}, 'Probar runtime distribuido'),
            e('button', {className:'secondary', onClick:()=>action('Preproceso', () => json(routes.preprocess, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text:form.text || 'Preparar contexto con nodos Android autorizados.', max_chunk_chars:1200, wait_timeout:35})}))}, 'Preprocesar en nodos'),
            e('button', {className:'secondary', onClick:()=>action('Router', () => json(routes.router, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({intent:form.intent, urgency:form.urgency})}))}, 'Router'),
            e('a', {className:'btn secondary', href:'/downloads/triade-android-node.apk'}, 'Descargar Android Node'),
            e('details', null,
              e('summary', null, 'Herramientas ocasionales'),
              e('button', {className:'secondary', onClick:()=>action('Health', () => json(routes.health))}, 'Health completo'),
              e('button', {className:'secondary', onClick:()=>action('Compatibilidad', () => json(routes.compat))}, 'Compatibilidad'),
              e('button', {className:'secondary', onClick:()=>action('Cola modelos', () => json(routes.queue))}, 'Cola modelos'),
              e('button', {className:'secondary', onClick:()=>action('Memoria semántica', () => json(routes.semantic))}, 'Memoria semántica'),
              e('button', {className:'ghost', onClick:()=>setChat([])}, 'Limpiar chat')
            ),
            e('div', {className:'box'}, log)
          )
        ),
        e('section', {className:'main'},
          e('div', {className:'alert'},
            e('span', {className:'dot ' + level}),
            e('div', null, e('div', {className:'status ' + level}, alertText), e('div', {className:'small'}, issues.length ? issues.join(' · ') : 'Ollama, Docker, RAM y nodos listos.')),
            e('div', {className:'organs'}, ['Central','Hipotálamo','Bodega','Federación'].map((name, i) => e('span', {key:name, className:'organ ' + ((i < 3 ? local.ollama?.ok : nodes.length) ? 'on' : '')}, name)))
          ),
          e('section', {className:'chat'}, chat.map((m, i) => e('div', {key:i, className:'msg ' + (m.who === 'user' ? 'user' : 'bot')}, m.text, m.meta ? e('div', {className:'meta'}, m.meta) : null))),
          e('div', {className:'composer'},
            e('textarea', {value:form.text, placeholder:'Escribe... Ctrl+Enter', onChange:ev=>setField('text', ev.target.value), onKeyDown:ev=>{if(ev.key==='Enter' && (ev.ctrlKey || ev.metaKey)) send();}}),
            e('button', {onClick:send, disabled:busy}, busy ? '...' : 'Enviar')
          )
        ),
        e('aside', {className:'panel right'},
          e('div', {className:'section', style:{borderTop:0, marginTop:0, paddingTop:0}}, e('h2', null, 'Pulso vivo'),
            alerts.length ? e('div', {className:'box'}, alerts.map(item => item.name + ': ' + item.summary).join('\n')) : e('div', {className:'box'}, 'Sin alertas activas.'),
            e('div', {className:'grid'},
              e(PanelMetric, {value:String(lifeCounters.cycles || 0), label:'ciclos internos', tone:life.status === 'degraded' ? 'critical' : 'ready', hint:'cada ' + (life.interval_seconds || '--') + ' s'}),
              e(PanelMetric, {value:String(lifeCounters.actions_observed || 0), label:'acciones observadas', tone:'ready', hint:Object.keys(lifeActions).slice(0,3).join(', ')}),
              e(PanelMetric, {value:lifeIntegrity.ok ? 'ok' : 'pendiente', label:'integridad', tone:lifeIntegrity.ok ? 'ready' : 'critical', hint:'runs ' + (lifeIntegrity.counts?.runs || 0)}),
              e(PanelMetric, {value:String(lifeCounters.learning_candidates_seen || 0), label:'candidatos detectados', tone:'ready', hint:String(lifeCounters.neuron_proposals_seen || 0) + ' neuronas propuestas'}),
              e(PanelMetric, {value:semanticAlignment.has_stable_semantic_memory ? 'estable' : 'sin stable', label:'memoria semántica', tone:semanticAlignment.has_stable_semantic_memory ? 'ready' : 'critical', hint:(semanticAlignment.total_documents || 0) + ' documentos · ' + (semanticAlignment.embeddings || 0) + ' embeddings'}),
              e(PanelMetric, {value:qualia.status || '--', label:'Qualia', tone:qualia.status === 'ok' ? 'ready' : 'critical', hint:'pulso + memoria + órganos'}),
              e(PanelMetric, {value: hardware.tier || '--', label:'PC local', tone: hardware.tier === 'low' ? 'critical' : 'ready', hint:n(hardware.ram_available_gb) + ' GB RAM libre'}),
              e(PanelMetric, {value:String(nodes.length || 0), label:'nodos que alimentan', tone:nodes.length ? 'ready' : 'critical', hint:String(authorized.runtime_node_count || totals.devices || 0) + ' runtime'}),
              e(PanelMetric, {value:String(authorized.cpu_authorized_count || totals.cpu_authorized || 0), label:'CPU autorizada', tone:'ready'}),
              e(PanelMetric, {value:n(authorized.ram_authorized_gb || totals.ram_authorized_gb), label:'GB RAM federada', tone:(authorized.ram_authorized_gb || totals.ram_authorized_gb || 0) >= 4 ? 'ready' : 'critical'}),
              e(PanelMetric, {value:n(authorized.vram_authorized_gb || totals.vram_authorized_gb || 0), label:'GB VRAM/GPU', tone:(authorized.vram_authorized_gb || totals.vram_authorized_gb || 0) > 0 ? 'ready' : 'critical'}),
              e(PanelMetric, {value:String(authorized.llm_hosts || totals.llm_hosts || 0), label:'hosts LLM Android', tone:(authorized.llm_hosts || totals.llm_hosts || 0) ? 'ready' : 'critical'}),
              e(PanelMetric, {value:local.ollama?.ok ? 'activo' : 'apagado', label:'Ollama local', tone:local.ollama?.ok ? 'ready' : 'critical'}),
              e(PanelMetric, {value:local.docker?.ok ? 'activo' : (local.docker?.installed ? 'instalado' : 'pendiente'), label:'Docker', tone:local.docker?.ok ? 'ready' : 'critical', hint:local.docker?.engine || local.docker?.version || ''})
            )
          ),
          e('div', {className:'section'}, e('h2', null, 'Aprendizaje en segundo plano'),
            e('div', {className:'box'}, [
              'estado: ' + (life.running ? 'activo' : 'snapshot'),
              'qualia: ' + (qualia.status || '--'),
              'semántica: ' + (semanticAlignment.message_to_central || '--'),
              'fallback: ' + (lifeReflection.fallback_percent ?? '--') + '%',
              'Q promedio: ' + (lifeReflection.avg_q_crystal ?? '--'),
              'propuestas: ' + ((lifeReflection.neuron_proposals || []).join(', ') || 'sin propuestas'),
              'politica: ' + (life.policy?.background_learning || 'candidate_detection_only')
            ].join('\\n'))
          ),
          e('div', {className:'section'}, e('h2', null, 'Modelos por suma'), runnable.length ? runnable.map(item => e('span', {className:'pill ok', key:item.model}, item.model)) : e('div', {className:'empty'}, 'La suma de RAM ayuda a preparar trabajos, pero aún no hospeda inferencia LLM única.')),
          e('div', {className:'section'}, e('h2', null, 'Nodos federados reales'),
            nodes.length ? nodes.map(node => e('div', {className:'node ready', key:node.node_id},
              e('div', {className:'node-head'}, e('b', null, node.name || node.device_name || node.node_id), e('span', {className:'tag'}, (Number(node.resource_limit_percent || 0) >= 100 ? 'dedicado' : String(node.resource_limit_percent || 0) + '%'))),
              e('div', {className:'small'}, 'CPU ' + (node.cpu_authorized_count || node.cpu_authorized || 0) + '/' + (node.cpu_count || '?') + ' · RAM ' + n(node.ram_authorized_gb) + '/' + n(node.ram_available_gb) + ' GB'),
              e('div', {className:'small'}, (node.capabilities?.app_version || node.app_version || '?') + ' · ' + (node.transport || node.capabilities?.source || 'local') + ' · ' + (node.can_host_llm ? 'hospeda LLM' : 'no hospeda LLM')),
              e('div', {className:'small'}, node.resource_limit_reported ? 'modo reportado por APK' : 'modo dedicado asumido: relay sin campos nuevos')
            )) : e('div', {className:'empty'}, 'Ningún Android nativo online con jobs.')
          ),
          e('div', {className:'live'}, 'Sincronización cada 15 s. Browser no cuenta como nodo; solo Android nativo con CPU/RAM/GPU autorizada.')
        )
      );
    }

    ReactDOM.createRoot(document.getElementById('root')).render(e(App));
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    return TRIADE_REACT_UI_HTML
