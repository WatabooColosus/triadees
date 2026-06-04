"""Tríade Ω Single Port App.

Puerto único 8010 para UI, health, router, compatibilidad, memoria semántica y runs locales.
"""

from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from triade.core.runner import TriadeRunner
from triade.core.repo_info import repo_info
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

app = FastAPI(title="Tríade Ω Single Port", version="0.9.0")
ANDROID_APK_PATH = Path(os.environ.get("TRIADE_ANDROID_APK", "apps/static/triade-android-node.apk"))
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
        "runnable_models": runnable,
        "feed_targets": feed_only,
        "missing_for_comfortable_models": missing,
        "capabilities": caps,
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
    federated_authorized = {
        "device_count": len(online_feeders),
        "cpu_authorized_count": sum(int(node.get("cpu_authorized_count") or 0) for node in online_feeders),
        "ram_authorized_gb": round(sum(float(node.get("ram_authorized_gb") or 0.0) for node in online_feeders), 2),
        "ram_available_gb": round(sum(float(node.get("ram_available_gb") or 0.0) for node in online_feeders), 2),
    }
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
    docker = tool_status("docker", ["docker", "--version"])
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
            "llm_hosts": [node for node in nodes if node["can_host_llm"]],
        },
        "constants": {
            "router": "single-port ModelRouter activo en /api/router/doctor",
            "docker": "disponible" if docker["ok"] else "pendiente/no disponible",
            "relay": "public relay Railway",
            "policy": "solo dispositivos nativos/autorizados que invierten CPU/RAM/GPU cuentan como nodos federados",
        },
    }


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, Any]:
    runner = TriadeRunner(use_ollama=False)
    hardware, ollama = system_payload()
    return {
        "status": "ok", "entity": "Tríade Ω", "mode": "single-port", "port": 8010,
        "security": {"api_key_required": bool(os.getenv("TRIADE_API_KEY"))},
        "repo": repo_info(), "hardware": hardware.to_dict(), "ollama": ollama, "doctor": runner.doctor(),
    }


@app.post("/api/router/doctor")
def route_doctor(request: RouterRequest) -> dict[str, Any]:
    return router_payload(intent=request.intent, urgency=request.urgency)


@app.get("/api/models/compatibility")
def model_compatibility() -> dict[str, Any]:
    hardware, ollama = system_payload()
    matrix = ModelCompatibilityMatrix(hardware=hardware, available_models=ollama.get("models", []))
    return {"status": "ok", "mode": "single-port", "ollama": ollama, "matrix": matrix.build()}


@app.get("/api/models/install-queue")
def model_install_queue(include_allowed: bool = False) -> dict[str, Any]:
    hardware, ollama = system_payload()
    queue = ModelInstallQueue(hardware=hardware, available_models=ollama.get("models", []))
    return queue.build(include_allowed=include_allowed)


@app.get("/api/system/model-capacity")
def system_model_capacity(sync_relay: bool = False) -> dict[str, Any]:
    return build_model_capacity(sync_relay=sync_relay)


@app.get("/downloads/triade-android-node.apk")
def download_android_node_apk() -> FileResponse:
    if not ANDROID_APK_PATH.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="APK Android no encontrado.")
    return FileResponse(
        ANDROID_APK_PATH,
        media_type="application/vnd.android.package-archive",
        filename="triade-android-node.apk",
    )


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
            capabilities["last_benchmark"] = request.result
            capabilities["benchmark_score"] = int(request.result.get("score") or capabilities.get("benchmark_score") or 0)
            capabilities["compute_status"] = "ready"
            federation.update_capabilities(request.node_id, capabilities)
    return {"status": "ok", "job_id": job_id, "accepted": True}


@app.post("/api/local-federation/benchmark")
def local_federation_benchmark(seconds: float = 1.0, wait_timeout: float = 25.0) -> dict[str, Any]:
    federation = Federation()
    nodes = [
        node
        for node in federation.list_nodes(status="active")
        if (node.get("capabilities") or {}).get("federation_complete")
        and (node.get("capabilities") or {}).get("online")
    ]
    if not nodes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay dispositivos federados locales online.")
    node = nodes[0]
    job = create_local_job(str(node["node_id"]), task="browser_benchmark", seconds=seconds)
    result = wait_local_job(str(job["job_id"]), timeout=wait_timeout)
    return {"status": "ok" if result.get("status") == "completed" else result.get("status"), "node_id": node["node_id"], "job": result}


@app.get("/api/semantic/doctor")
def semantic_doctor() -> dict[str, Any]:
    return SemanticEmbeddingEngine().doctor()


@app.get("/api/semantic/governance/doctor")
def semantic_governance_doctor() -> dict[str, Any]:
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


@app.post("/api/run")
@app.post("/triade/run")
def run_triade(request: RunRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
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
        context=request.context,
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
<button onclick='save()'>Guardar</button><button class='secondary' onclick='health()'>Health 8010</button><button class='secondary' onclick='capacity()'>Capacidad y nodos</button><button class='secondary' onclick='router()'>Consultar Router</button><button class='secondary' onclick='compat()'>Compatibilidad</button><button class='secondary' onclick='installQueue()'>Cola modelos</button><button class='secondary' onclick='semanticDoctor()'>Memoria semántica</button><button class='secondary' onclick='apply()'>Aplicar recomendados</button><button class='secondary' onclick='clearChat()'>Limpiar</button><div id='box' class='box'>Sin consultar.</div>
</aside><main class='card main'><div class='top'><b>Chat local auditable</b><br><span id='status'>Listo</span></div><section id='chat' class='chat'></section><div class='composer'><textarea id='msg' placeholder='Escribe... Ctrl+Enter' onkeydown='keysend(event)'></textarea><button onclick='send()'>Enviar</button></div></main></div>
<script>
const $=id=>document.getElementById(id);let lastRouter=null;const settings=['key','hyp','cen','intent','urgency','project','neuron','session','scope'];function save(){settings.forEach(k=>localStorage.setItem('triade_sp_'+k,$(k).value));localStorage.setItem('triade_sp_ollama',$('ollama').checked);localStorage.setItem('triade_sp_auto',$('auto').checked);status('Guardado',true)}function load(){settings.forEach(k=>{const v=localStorage.getItem('triade_sp_'+k);if(v!==null)$(k).value=v});$('ollama').checked=localStorage.getItem('triade_sp_ollama')==='true';$('auto').checked=localStorage.getItem('triade_sp_auto')!=='false'}function status(t,ok=false){$('status').textContent=t;$('status').className=ok?'ok':''}function add(cls,text,meta=''){let d=document.createElement('div');d.className='msg '+cls;d.textContent=text;if(meta){let m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}$('chat').appendChild(d);$('chat').scrollTop=$('chat').scrollHeight}function context(){let c={};if($('project').value.trim())c.project_id=$('project').value.trim();if($('neuron').value.trim())c.active_neuron=$('neuron').value.trim();if($('session').value.trim())c.session_id=$('session').value.trim();if($('scope').value)c.context_scope=$('scope').value;return c}
async function health(){try{let r=await fetch('/api/health');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({mode:j.mode,hardware:j.hardware,contexts:j.doctor?.crystal_contexts,ollama:j.ollama?.ok,runs:j.doctor?.counts?.runs},null,2);status('Health OK',true)}catch(e){status('Health falló: '+e.message)}}
async function router(){try{let r=await fetch('/api/router/doctor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intent:$('intent').value,urgency:$('urgency').value})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);lastRouter=j;let d=j.router.decisions;$('box').textContent=JSON.stringify({central:d.central?.selected_model,hypothalamus:d.hypothalamus?.selected_model,fast:d.fast?.selected_model,deep:d.deep?.selected_model},null,2);status('Router OK',true)}catch(e){status('Router falló: '+e.message)}}
async function compat(){try{let r=await fetch('/api/models/compatibility');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.matrix.summary,counts:j.matrix.counts,models:j.matrix.models},null,2);status('Compatibilidad OK',true)}catch(e){status('Compatibilidad falló: '+e.message)}}
async function installQueue(){try{let r=await fetch('/api/models/install-queue?include_allowed=false');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.summary,count:j.count,policy:j.policy,candidates:j.candidates},null,2);status('Cola OK',true)}catch(e){status('Cola falló: '+e.message)}}
async function capacity(){try{let r=await fetch('/api/system/model-capacity?sync_relay=true');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);box.textContent=JSON.stringify({pc:{tier:j.local.hardware.tier,ram_free:j.local.hardware.ram_available_gb,ollama:j.local.ollama.ok,docker:j.local.docker.ok,missing:j.local.missing_for_comfortable_models,counts:j.local.counts},nodos:j.federation.nodes.map(n=>({name:n.name,node_id:n.node_id,online:n.online,native_android:n.native_android,cpu:n.cpu_count,ram_free:n.ram_available_gb,score:n.benchmark_score,use:n.recommended_use,feed:n.can_feed_local_models,host:n.can_host_llm,missing:n.missing_for_comfortable_models})),constantes:j.constants},null,2);status('Capacidad actualizada',true)}catch(e){status('Capacidad falló: '+e.message)}}
async function semanticDoctor(){try{let r=await fetch('/api/semantic/governance/doctor');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify(j,null,2);status('Gobierno semántico consultado',true)}catch(e){status('Memoria semántica falló: '+e.message)}}
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
<div class='section'><h2>Acciones</h2><button onclick='capacity(true)'>Actualizar pulso</button><button class='secondary' onclick='router()'>Recomendar modelos</button><a href='/downloads/triade-android-node.apk'><button class='secondary' type='button'>Descargar Android Node</button></a><details><summary>Herramientas ocasionales</summary><button class='secondary' onclick='health()'>Health completo</button><button class='secondary' onclick='compat()'>Compatibilidad</button><button class='secondary' onclick='installQueue()'>Cola modelos</button><button class='secondary' onclick='semanticDoctor()'>Memoria semántica</button><button class='ghost' onclick='apply()'>Aplicar recomendados</button><button class='ghost' onclick='clearChat()'>Limpiar chat</button></details><div id='box' class='box'>Pulso inicial pendiente.</div></div></aside>
<main class='main'><div class='top'><div><b>Chat local auditable</b><br><span id='status' class='muted'>Iniciando pulso...</span></div><div class='organs'><span id='orgCentral' class='organ'>Central</span><span id='orgHyp' class='organ'>Hipotálamo</span><span id='orgMem' class='organ'>Bodega</span><span id='orgFed' class='organ'>Federación</span></div></div><section id='chat' class='chat'></section><div class='composer'><textarea id='msg' placeholder='Escribe... Ctrl+Enter' onkeydown='keysend(event)'></textarea><button onclick='send()'>Enviar</button></div></main>
<aside class='pulse'><h2>Pulso vivo</h2><div id='summary' class='grid2'><div class='metric'><b>...</b><span>PC</span></div><div class='metric'><b>...</b><span>Nodos</span></div></div><div id='missing' class='section'></div><div class='section'><h2>Modelos</h2><div id='models' class='model-list'><span class='empty'>Sin lectura todavía.</span></div></div><div class='section'><h2>Nodos que alimentan</h2><div id='nodes'><span class='empty'>Sin nodos sincronizados.</span></div></div><div class='live-line' id='liveLine'>Sincronización cada 15 s.</div></aside>
</div><script>
const $=id=>document.getElementById(id);let lastRouter=null,lastCapacity=null;const settings=['key','hyp','cen','intent','urgency','project','neuron','session','scope'];function save(){settings.forEach(k=>localStorage.setItem('triade_sp_'+k,$(k).value));localStorage.setItem('triade_sp_ollama',$('ollama').checked);localStorage.setItem('triade_sp_auto',$('auto').checked);status('Estado guardado',true)}function load(){settings.forEach(k=>{const v=localStorage.getItem('triade_sp_'+k);if(v!==null)$(k).value=v});$('ollama').checked=localStorage.getItem('triade_sp_ollama')==='true';$('auto').checked=localStorage.getItem('triade_sp_auto')!=='false'}function status(t,ok=false){$('status').textContent=t;$('status').className=ok?'oktxt':'muted'}function add(cls,text,meta=''){let d=document.createElement('div');d.className='msg '+cls;d.textContent=text;if(meta){let m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}$('chat').appendChild(d);$('chat').scrollTop=$('chat').scrollHeight}function context(){let c={};if($('project').value.trim())c.project_id=$('project').value.trim();if($('neuron').value.trim())c.active_neuron=$('neuron').value.trim();if($('session').value.trim())c.session_id=$('session').value.trim();if($('scope').value)c.context_scope=$('scope').value;return c}
function fmt(n){return Number.isFinite(Number(n))?Number(n).toFixed(1):'--'}function cls(ok){return ok?'oktxt':'badtxt'}function setOrgan(id,on){$(id).className='organ '+(on?'ok':'')}function briefMissing(items){return (items||[]).slice(0,4).map(x=>`<div class='metric critical'><b>Falta</b><span>${x}</span></div>`).join('')||`<div class='metric ready'><b>Listo</b><span>Sin bloqueos principales.</span></div>`}
function renderCapacity(j){lastCapacity=j;let h=j.local.hardware, f=j.federation, feeders=f.online_feeders||[], hosts=f.llm_hosts||[], a=f.authorized||{};$('liveDot').className='state-dot ok';setOrgan('orgCentral',j.local.ollama.ok);setOrgan('orgHyp',j.local.ollama.ok);setOrgan('orgMem',true);setOrgan('orgFed',feeders.length>0);$('summary').innerHTML=`<div class='metric ${h.tier==='low'?'critical':'ready'}'><b>${h.tier}</b><span>PC local · ${fmt(h.ram_available_gb)} GB RAM libre</span></div><div class='metric ${feeders.length?'ready':'critical'}'><b>${feeders.length}</b><span>dispositivos federados · ${hosts.length} hosts LLM</span></div><div class='metric ${feeders.length?'ready':'critical'}'><b>${a.cpu_authorized_count||0}</b><span>CPU autorizada federada</span></div><div class='metric ${feeders.length?'ready':'critical'}'><b>${fmt(a.ram_authorized_gb)}</b><span>GB RAM autorizada federada</span></div><div class='metric'><b class='${cls(j.local.ollama.ok)}'>${j.local.ollama.ok?'activo':'apagado'}</b><span>Ollama</span></div><div class='metric'><b class='${cls(j.local.docker.ok)}'>${j.local.docker.ok?'listo':'pendiente'}</b><span>Docker</span></div>`;$('missing').innerHTML=`<h2>Qué falta en PC local</h2>${briefMissing(j.local.missing_for_comfortable_models)}`;$('models').innerHTML=[...(j.local.recommended_models||[]).map(m=>`<span class='pill oktxt'>${m.model}</span>`),...(j.local.allowed_models||[]).map(m=>`<span class='pill'>${m.model}</span>`)].join('')||'<span class="empty">No hay modelos recomendados para este estado.</span>';$('nodes').innerHTML=feeders.map(n=>{let source=n.resource_limit_reported?'reportado por app':'asumido: relay no envio porcentaje';return `<div class='node ready'><div class='node-head'><b>${n.name||n.node_id}</b><span class='tag'>${n.resource_limit_percent||0}% ${n.resource_limit_reported?'autorizado':'asumido'}</span></div><div class='hint'>CPU ${n.cpu_authorized_count}/${n.cpu_count} · RAM ${fmt(n.ram_authorized_gb)}/${fmt(n.ram_available_gb)} GB · score ${n.benchmark_score||0}</div><div class='hint'>app ${n.capabilities?.app_version||'?'} · ${source} · ${n.capabilities?.source||'local'}</div><div class='hint'><span class='feed'>invierte estructura en el modelo local</span> · <span class='host'>${n.can_host_llm?'hospeda LLM':'no hospeda LLM'}</span></div></div>`}).join('')||'<span class="empty">Ningún dispositivo federado autorizado online.</span>';$('box').textContent=`PC local ${h.tier}: ${fmt(h.ram_available_gb)} GB libres. Federación autorizada: ${a.cpu_authorized_count||0} CPU y ${fmt(a.ram_authorized_gb)} GB RAM en ${feeders.length} dispositivo(s). Hosts LLM ${hosts.length}.`;let now=new Date().toLocaleTimeString();$('liveLine').textContent=`Último pulso ${now} · relay ${f.relay?.has_admin_token?'sincronizado':'sin token admin'} · browser no cuenta como nodo`;status('Pulso actualizado',true)}
async function capacity(manual=false){try{let r=await fetch('/api/system/model-capacity?sync_relay=true');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);renderCapacity(j);if(manual)add('bot','Pulso vivo actualizado: revisé PC, modelos, nodos y constantes.')}catch(e){$('liveDot').className='state-dot';status('Pulso falló: '+e.message);$('box').textContent='Error de pulso: '+e.message}}
async function health(){try{let r=await fetch('/api/health');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({mode:j.mode,hardware:j.hardware,contexts:j.doctor?.crystal_contexts,ollama:j.ollama?.ok,runs:j.doctor?.counts?.runs},null,2);status('Health OK',true)}catch(e){status('Health falló: '+e.message)}}async function router(){try{let r=await fetch('/api/router/doctor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intent:$('intent').value,urgency:$('urgency').value})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);lastRouter=j;let d=j.router.decisions;$('box').textContent=JSON.stringify({central:d.central?.selected_model,hypothalamus:d.hypothalamus?.selected_model,fast:d.fast?.selected_model,deep:d.deep?.selected_model},null,2);status('Router OK',true)}catch(e){status('Router falló: '+e.message)}}async function compat(){try{let r=await fetch('/api/models/compatibility');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.matrix.summary,counts:j.matrix.counts,models:j.matrix.models},null,2);status('Compatibilidad OK',true)}catch(e){status('Compatibilidad falló: '+e.message)}}async function installQueue(){try{let r=await fetch('/api/models/install-queue?include_allowed=false');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.summary,count:j.count,policy:j.policy,candidates:j.candidates},null,2);status('Cola OK',true)}catch(e){status('Cola falló: '+e.message)}}async function semanticDoctor(){try{let r=await fetch('/api/semantic/governance/doctor');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify(j,null,2);status('Gobierno semántico consultado',true)}catch(e){status('Memoria semántica falló: '+e.message)}}function apply(){if(!lastRouter){status('Consulta router primero');return}let d=lastRouter.router.decisions;if(d.hypothalamus?.selected_model)$('hyp').value=d.hypothalamus.selected_model;if(d.central?.selected_model)$('cen').value=d.central.selected_model;$('ollama').checked=true;$('auto').checked=false;save();status('Recomendados aplicados',true)}
async function send(){save();let text=$('msg').value.trim();if(!text)return;$('msg').value='';add('user',text);status('Procesando...');try{let r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':$('key').value},body:JSON.stringify({text,source:'single-port-ui',use_ollama:$('ollama').checked,hypothalamus_model:$('hyp').value,central_model:$('cen').value,auto_select_models:$('auto').checked,context:context()})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);let t=j.crystal_temporal_state||{};add('bot',j.response,[j.run_id,'Q '+t.status,'scope '+t.context_scope,'ctx '+t.context_key,'H '+j.models?.hypothalamus?.name,'C '+j.models?.central?.name].filter(Boolean).join(' · '));status('Respuesta recibida',true);capacity(false)}catch(e){add('bot','Error: '+e.message);status('Error')}}function clearChat(){$('chat').innerHTML=''}function keysend(e){if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))send()}load();add('bot','Tríade Ω lista. Mantengo pulso vivo de PC, modelos y nodos.');capacity(false);setInterval(()=>capacity(false),15000);
</script></body></html>
"""


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    return TRIADE_UI_HTML
