"""Tríade Ω — Capa de servicios (modelos y helpers de negocio).

Contiene toda la lógica pura de la single_port_app,
sin dependencias de FastAPI. Los route handlers en
apps/routes/ importan desde aquí.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

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
from triade.federation.edge_router import EdgeRouter
from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_search import SemanticSearchEngine
from triade.models.compatibility_matrix import ModelCompatibilityMatrix
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_install_queue import ModelInstallQueue
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient

# ── Constantes de ruta ────────────────────────────────────────────────

ANDROID_APK_PATH = Path(os.environ.get("TRIADE_ANDROID_APK", "apps/static/triade-android-node.apk"))
ANDROID_RUNTIME_DIR = Path(os.environ.get("TRIADE_ANDROID_RUNTIME_DIR", "apps/static/android-runtime"))
ANDROID_LLAMA_CLI_PATH = Path(
    os.environ.get("TRIADE_ANDROID_LLAMA_CLI", str(ANDROID_RUNTIME_DIR / "llama-cli"))
)
ANDROID_BASE_MODEL_PATH = Path(
    os.environ.get("TRIADE_ANDROID_BASE_MODEL", str(ANDROID_RUNTIME_DIR / "triade-base.gguf"))
)

LOCAL_JOBS: dict[str, dict[str, Any]] = {}

# ── Modelos Pydantic ───────────────────────────────────────────────────


class RunRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source: str = "single-port-ui"
    use_ollama: bool = True
    hypothalamus_model: str | None = None
    central_model: str | None = None
    auto_select_models: bool = True
    context: dict[str, Any] = Field(default_factory=dict)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)
    conversation_history: list[dict[str, str]] = Field(default_factory=list)
    # El chat usa por defecto el ciclo semántico general: recuperar por
    # similitud, aplicar gobernanza y permitir influencia solo a recuerdos
    # verificados. No contiene reglas especiales por pregunta o dato.
    semantic_recall_enabled: bool = True
    semantic_model: str | None = None
    semantic_limit: int = Field(default=3, ge=1, le=20)
    semantic_min_similarity: float = Field(default=0.55, ge=-1.0, le=1.0)
    semantic_domain: str | None = None
    semantic_allow_experimental: bool = False
    debug: bool = False


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

# ── Helpers de negocio ─────────────────────────────────────────────────


def clean_model(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def system_payload() -> tuple[object, dict[str, Any]]:
    hardware = HardwareProfiler().detect()
    ollama = OllamaClient().health()
    return hardware, ollama


def router_payload(intent: str = "conversation", urgency: str = "medium") -> dict[str, Any]:
    hardware, ollama = system_payload()
    router = ModelRouter(available_models=ollama.get("models", []), hardware=hardware)
    return {
        "status": "ok",
        "mode": "single-port",
        "hardware": hardware.to_dict(),
        "ollama": ollama,
        "router": router.route_many(intent=intent, urgency=urgency),
    }


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
        return dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return {}


def save_local_node_tokens(tokens: dict[str, str]) -> None:
    path = local_node_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(tokens, indent=2, ensure_ascii=False), encoding="utf-8")


def local_node_capabilities(node_id: str, capabilities: dict[str, Any]) -> dict[str, Any]:
    return relay_capabilities_for_federation(
        {"node_id": node_id, "online": True, "capabilities": capabilities},
        "http://127.0.0.1:8010",
    )


def upsert_local_android_node(
    node_id: str, name: str, capabilities: dict[str, Any]
) -> dict[str, Any]:
    return Federation().register_node(
        node_id=node_id,
        name=name,
        owner="single-port-local",
        endpoint="http://127.0.0.1:8010",
        trust_level="medium",
        permissions=["publish_capabilities", "request_compute"],
        capabilities=local_node_capabilities(node_id, capabilities),
    )


def create_local_job(
    node_id: str,
    task: str,
    payload: dict[str, Any] | None = None,
    seconds: float = 1.0,
) -> dict[str, Any]:
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


def wait_local_job(
    job_id: str, timeout: float = 25.0, interval: float = 0.5, sandbox_fallback: bool = True
) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = LOCAL_JOBS.get(job_id) or {}
        if job.get("status") in {"completed", "failed"}:
            return job
        time.sleep(interval)
    job = LOCAL_JOBS.get(job_id) or {"job_id": job_id}
    # Si nadie recogio el job y es sandbox, ejecutarlo localmente en aislamiento
    if sandbox_fallback and job.get("task") in SAFE_SANDBOX_TASKS:
        from triade.sandbox import run_in_sandbox

        sb = run_in_sandbox(job["task"], job.get("payload"), timeout=max(timeout, 15.0))
        if sb.get("sha256"):
            job["result"] = {"sha256": sb["sha256"]}
            job["status"] = "completed"
        elif sb.get("score"):
            job["result"] = {"score": sb["score"], "ops": sb.get("ops", 0)}
            job["status"] = "completed"
        elif sb.get("word_count") is not None:
            job["result"] = {"word_count": sb["word_count"], "char_count": sb["char_count"], "approx_tokens": sb["approx_tokens"]}
            job["status"] = "completed"
        elif sb.get("ops"):
            job["result"] = {"ops": sb["ops"]}
            job["status"] = "completed"
        elif sb.get("status") == "completed":
            job["result"] = sb
            job["status"] = "completed"
        else:
            job["status"] = "sandbox_error"
            job["error"] = sb.get("error", "sandbox_fallback_failed")
        job["sandbox"] = sb.get("sandbox")
        job["updated_at"] = time.time()
        LOCAL_JOBS[job_id] = job
        return job
    job["status"] = "timeout"
    job["error"] = "Tiempo de espera agotado esperando al nodo local."
    return job


SAFE_SANDBOX_TASKS = frozenset({"sha256", "echo", "preprocess_text", "federated_inference_probe", "browser_benchmark"})

TASK_PERMISSIONS: dict[str, str] = {
    "browser_benchmark": "request_compute",
    "preprocess_text": "request_compute",
    "federated_inference_probe": "request_compute",
    "android_model_doctor": "request_compute",
    "android_local_generate": "request_compute",
}

TRUST_THRESHOLDS: dict[str, str] = {
    "federated_inference_probe": "low",
    "android_model_doctor": "medium",
    "android_local_generate": "medium",
}

TRUST_RANK = {"low": 0, "medium": 1, "high": 2}


def _node_meets_federation_gate(node: dict[str, Any], task: str | None, fed: Federation) -> bool:
    """Verifica que el nodo tenga el permiso y trust level requeridos por el gate."""
    if task is None:
        return True
    required_perm = TASK_PERMISSIONS.get(task)
    min_trust = TRUST_THRESHOLDS.get(task)
    if required_perm is None and min_trust is None:
        return True
    registered = fed.get_node(node["node_id"])
    if registered is None:
        return False
    perms = registered.get("permissions") or []
    if required_perm and required_perm not in perms:
        return False
    if min_trust:
        trust = registered.get("trust_level") or "low"
        if TRUST_RANK.get(trust, 0) < TRUST_RANK.get(min_trust, 0):
            return False
    return True


def local_federated_nodes(task: str | None = None) -> list[dict[str, Any]]:
    fed = Federation()
    nodes = []
    for node in fed.list_nodes(status="active"):
        caps = node.get("capabilities") or {}
        allowed = (
            caps.get("allowed_tasks") if isinstance(caps.get("allowed_tasks"), list) else []
        )
        relay_url = str(caps.get("relay_url") or node.get("endpoint") or "")
        is_direct_local = (
            "127.0.0.1:8010" in relay_url
            or "localhost:8010" in relay_url
            or "192.168." in relay_url
        )
        if not (caps.get("federation_complete") and caps.get("online")):
            continue
        if not is_direct_local:
            continue
        if task and task not in allowed:
            continue
        if not _node_meets_federation_gate(node, task, fed):
            continue
        nodes.append(node)
    return nodes


def android_llm_host_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hosts = []
    for node in nodes:
        caps = node.get("capabilities") or {}
        support = caps.get("model_support") or {}
        allowed = (
            caps.get("allowed_tasks") if isinstance(caps.get("allowed_tasks"), list) else []
        )
        if "android_local_generate" not in allowed:
            continue
        if bool(
            support.get("can_host_llm")
            or caps.get("can_run_local_llm")
            or caps.get("local_model_runtime_ready")
        ):
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
                keyword_counts[term] = (
                    keyword_counts.get(term, 0) + int(keyword.get("count") or 0)
                )
        for chunk in result.get("chunks") or []:
            if isinstance(chunk, dict):
                chunks.append(
                    {**chunk, "node_id": job.get("node_id"), "source_job_id": job.get("job_id")}
                )
    keywords = [
        {"term": term, "count": count}
        for term, count in sorted(keyword_counts.items(), key=lambda pair: (-pair[1], pair[0]))[
            :24
        ]
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
        return {
            "installed": True,
            "path": path,
            "ok": result.returncode == 0,
            "version": text[0] if text else "unknown",
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "installed": True,
            "path": path,
            "ok": False,
            "version": "error",
            "error": str(exc),
        }


def docker_status() -> dict[str, Any]:
    docker_path = shutil.which("docker")
    candidates = [
        Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"),
        Path(r"C:\Program Files\Docker\Docker\DockerCli.exe"),
    ]
    if not docker_path:
        docker_path = next((str(candidate) for candidate in candidates if candidate.exists()), None)
    if not docker_path:
        return {
            "installed": False,
            "path": None,
            "ok": False,
            "version": "not_found",
            "engine": "not_found",
        }
    try:
        version = subprocess.run(
            [docker_path, "--version"], capture_output=True, text=True, timeout=5, check=False
        )
        info = subprocess.run(
            [docker_path, "info", "--format", "{{json .ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
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
        return {
            "installed": True,
            "path": docker_path,
            "ok": False,
            "version": "error",
            "engine": "error",
            "error": str(exc),
        }


def node_model_readiness(node: dict[str, Any]) -> dict[str, Any]:
    caps = node.get("capabilities") or {}
    support = caps.get("model_support") or {}
    ram = float(caps.get("ram_available_gb") or caps.get("device_memory_gb") or 0.0)
    authorized_ram = float(
        caps.get("ram_authorized_gb") or support.get("authorized_ram_gb") or 0.0
    )
    cpu = int(caps.get("cpu_count") or 1)
    authorized_cpu = int(caps.get("cpu_authorized_count") or support.get("authorized_cpu_count") or 0)
    native_android = bool(caps.get("native_android"))
    can_host_llm = bool(support.get("can_host_llm"))
    federation_complete = bool(
        caps.get("federation_complete")
        or (native_android and caps.get("online") and authorized_cpu > 0)
    )
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
        "resource_limit_percent": int(
            caps.get("resource_limit_percent")
            or support.get("resource_limit_percent")
            or 0
        ),
        "resource_limit_reported": bool(
            caps.get("resource_limit_reported") or support.get("resource_limit_reported")
        ),
        "resource_limit_source": caps.get("resource_limit_source")
        or support.get("resource_limit_source")
        or "unknown",
        "federation_complete": federation_complete,
        "benchmark_score": caps.get("benchmark_score", 0),
        "recommended_use": support.get("recommended_use", "unknown"),
        "can_host_llm": can_host_llm,
        "can_feed_local_models": feed_ready,
        "edge_model_runtime": bool(caps.get("edge_model_runtime") or support.get("edge_model_runtime")),
        "model_runtime_backend": caps.get("model_runtime_backend")
        or support.get("model_runtime_backend")
        or "none",
        "local_model_runtime_ready": bool(
            caps.get("local_model_runtime_ready") or support.get("local_model_runtime_ready")
        ),
        "runnable_models": runnable,
        "feed_targets": feed_only,
        "missing_for_comfortable_models": missing,
        "capabilities": caps,
    }


def federated_model_plan(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    feeders = [
        node for node in nodes if node["can_feed_local_models"] and node["federation_complete"]
    ]
    runtime_ready = [
        node
        for node in feeders
        if "preprocess_text"
        in ((node.get("capabilities") or {}).get("allowed_tasks") or [])
        and (
            "127.0.0.1:8010" in str((node.get("capabilities") or {}).get("relay_url") or "")
            or "localhost:8010" in str((node.get("capabilities") or {}).get("relay_url") or "")
            or "192.168." in str((node.get("capabilities") or {}).get("relay_url") or "")
        )
    ]
    total_cpu = sum(int(node.get("cpu_authorized_count") or 0) for node in feeders)
    total_ram = round(sum(float(node.get("ram_authorized_gb") or 0.0) for node in feeders), 2)
    total_available_ram = round(
        sum(float(node.get("ram_available_gb") or 0.0) for node in feeders), 2
    )
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
        {
            "model": model,
            "estimated_ram_gb": required,
            "fits_aggregate_ram": total_ram >= required,
        }
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
    missing.append(
        "runtime distribuido de inferencia para sumar RAM entre dispositivos (llama.cpp RPC/worker propio)"
    )
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
            if task
            in {
                "preprocess_text",
                "federated_inference_probe",
                "android_model_doctor",
                "android_local_generate",
            }
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
        transport = (
            "lan_8010"
            if (
                "127.0.0.1:8010" in relay_url
                or "localhost:8010" in relay_url
                or "192.168." in relay_url
            )
            else "public_relay"
        )
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
            "lease_status": "llm_host_ready"
            if node.get("can_host_llm")
            else ("job_worker_ready" if tasks else "heartbeat_only"),
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
            relay_sync = PublicRelayClient(
                str(relay["url"]), str(relay["admin_token"]), timeout=12
            ).sync_nodes_to_federation(federation)
            relay_sync["attempted"] = True
        except Exception as exc:
            relay_sync = {"attempted": True, "status": "error", "error": str(exc)}
    nodes = [node_model_readiness(node) for node in federation.list_nodes(status="active")]
    online_feeders = [
        node for node in nodes if node["can_feed_local_models"] and node["federation_complete"]
    ]
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
            "relay": {
                "url": relay.get("url"),
                "has_admin_token": bool(relay.get("admin_token")),
                "sync": relay_sync,
            },
            "nodes": nodes,
            "online_feeders": online_feeders,
            "authorized": federated_authorized,
            "resource_lease": resource_lease,
            "llm_hosts": [node for node in nodes if node["can_host_llm"]],
        },
        "constants": {
            "router": "single-port ModelRouter activo en /api/router/doctor",
            "docker": "motor activo"
            if docker["ok"]
            else (
                "instalado, motor pendiente" if docker["installed"] else "pendiente/no disponible"
            ),
            "relay": "public relay Railway",
            "policy": "solo dispositivos nativos/autorizados que invierten CPU/RAM/GPU cuentan como nodos federados",
            "distributed_runtime": "jobs Android nativos: preprocess_text y federated_inference_probe alimentan al modelo local",
        },
    }


def _edge_llm_host_snapshot() -> list[dict]:
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


def _pulse_item(
    name: str, ok: bool, summary: str, detail: dict[str, Any] | None = None, level: str | None = None
) -> dict[str, Any]:
    clean_level = level or ("ok" if ok else "warn")
    return {"name": name, "ok": ok, "level": clean_level, "summary": summary, "detail": detail or {}}


def _safe_pulse(name: str, fn) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return _pulse_item(name, False, str(exc), level="error")


def _experimental_neuron_pulse() -> dict[str, Any]:
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
            "summary": {
                "experimental_neurons_with_evidence": 0,
                "total_activations": 0,
            },
            "last_active_neuron": None,
            "stable_ready_count": 0,
            "neurons": [],
            "error": str(exc),
            "policy": "evidence_only_no_auto_promotion",
        }


def _stable_readiness_pulse() -> dict[str, Any]:
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


def build_system_pulse(
    sync_relay: bool = True,
    intent: str = "conversation",
    urgency: str = "medium",
) -> dict[str, Any]:
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


def model_install_queue(include_allowed: bool = False) -> dict[str, Any]:
    hardware, ollama = system_payload()
    queue = ModelInstallQueue(hardware=hardware, available_models=ollama.get("models", []))
    return queue.build(include_allowed=include_allowed)


def semantic_governance_doctor() -> dict[str, Any]:
    return SemanticMemoryGovernance().doctor()


def federated_transport_doctor() -> dict[str, Any]:
    doctor = FederatedTransportDoctor()
    return doctor.model_dump() if hasattr(doctor, "model_dump") else doctor.dict()


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
            "gpu_names": [
                gpu.get("name") for gpu in hardware.get("gpus", []) if isinstance(gpu, dict)
            ],
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


def run_context_with_living_awareness(base_context: dict[str, Any]) -> dict[str, Any]:
    context = build_run_context_with_pulse(base_context, build_system_pulse)
    context["triade_operational_awareness"] = operational_awareness_context()
    return context
