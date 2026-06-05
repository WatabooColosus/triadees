"""Agente movil consentido para Termux/Android.

Expone un nodo local con limite cooperativo de uso. Android conserva el control
real de CPU, bateria y temperatura; este agente solo agenda trabajo dentro del
porcentaje objetivo configurado.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import secrets
import socket
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


DEFAULT_STATE_PATH = Path(os.environ.get("TRIADE_MOBILE_STATE", "mobile_node_state.json"))


@dataclass
class AgentConfig:
    node_id: str = "mobile-node"
    token: str = "change-me"
    target_usage_percent: int = 60
    max_workers: int = 2
    allow_jobs: bool = True
    battery_min_percent: int = 25
    admin_enabled: bool = False
    admin_root: str = "."
    allowed_commands: dict[str, list[str]] = field(default_factory=lambda: {
        "python_version": ["python", "--version"],
        "whoami": ["whoami"],
        "pwd": ["pwd"],
    })


@dataclass
class JobRecord:
    job_id: str
    task: str
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobRequest(BaseModel):
    task: str = Field(..., pattern="^(benchmark|sha256|echo)$")
    payload: dict[str, Any] = Field(default_factory=dict)
    seconds: float = Field(default=2.0, ge=0.1, le=30.0)


class ConfigRequest(BaseModel):
    target_usage_percent: int | None = Field(default=None, ge=5, le=90)
    max_workers: int | None = Field(default=None, ge=1, le=8)
    allow_jobs: bool | None = None
    battery_min_percent: int | None = Field(default=None, ge=5, le=95)
    admin_enabled: bool | None = None
    admin_root: str | None = None


class MobileNodeAgent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.jobs: dict[str, JobRecord] = {}
        self.work_queue: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self.workers: list[threading.Thread] = []
        self.started_at = time.time()

    def start(self) -> None:
        for index in range(self.config.max_workers):
            worker = threading.Thread(target=self._worker_loop, name=f"triade-mobile-worker-{index}", daemon=True)
            worker.start()
            self.workers.append(worker)

    def capabilities(self) -> dict[str, Any]:
        cpu_count = os.cpu_count() or 1
        return {
            "node_id": self.config.node_id,
            "agent": "triade-mobile-termux",
            "tier": self._tier(cpu_count),
            "cpu_count": cpu_count,
            "ram_total_gb": self._memory_total_gb(),
            "ram_available_gb": 0.0,
            "gpus": [],
            "target_usage_percent": self.config.target_usage_percent,
            "max_workers": self.config.max_workers,
            "allow_jobs": self.config.allow_jobs,
            "admin_enabled": self.config.admin_enabled,
            "admin_root": str(self._admin_root()),
            "allowed_commands": sorted(self.config.allowed_commands),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "uptime_seconds": round(time.time() - self.started_at, 2),
            "background_execution": True,
            "notes": [
                "Agente Termux consentido.",
                "Uso limitado por scheduler cooperativo.",
                "Android puede reducir rendimiento por bateria, temperatura o permisos.",
            ],
        }

    def submit(self, request: JobRequest) -> JobRecord:
        if not self.config.allow_jobs:
            raise ValueError("Jobs desactivados por configuracion local.")
        job = JobRecord(job_id=f"mjob-{uuid4().hex[:12]}", task=request.task)
        with self.lock:
            self.jobs[job.job_id] = job
            job.result = {"request": request.model_dump()}
        self.work_queue.put(job.job_id)
        return job

    def get_job(self, job_id: str) -> JobRecord | None:
        with self.lock:
            return self.jobs.get(job_id)

    def update_config(self, request: ConfigRequest) -> AgentConfig:
        if request.target_usage_percent is not None:
            self.config.target_usage_percent = request.target_usage_percent
        if request.max_workers is not None:
            self.config.max_workers = request.max_workers
        if request.allow_jobs is not None:
            self.config.allow_jobs = request.allow_jobs
        if request.battery_min_percent is not None:
            self.config.battery_min_percent = request.battery_min_percent
        if request.admin_enabled is not None:
            self.config.admin_enabled = request.admin_enabled
        if request.admin_root is not None:
            self.config.admin_root = request.admin_root
        save_config(self.config, DEFAULT_STATE_PATH)
        return self.config

    def list_files(self, rel_path: str = ".") -> dict[str, Any]:
        root = self._admin_root()
        target = self._resolve_admin_path(rel_path)
        if not target.exists():
            raise FileNotFoundError(str(rel_path))
        if not target.is_dir():
            raise NotADirectoryError(str(rel_path))
        entries = []
        for item in sorted(target.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower())):
            try:
                stat = item.stat()
            except OSError:
                continue
            entries.append({
                "name": item.name,
                "path": str(item.relative_to(root)),
                "type": "dir" if item.is_dir() else "file",
                "size": stat.st_size,
            })
        return {"root": str(root), "path": str(target.relative_to(root)), "entries": entries}

    def read_file(self, rel_path: str, max_bytes: int = 200_000) -> dict[str, Any]:
        target = self._resolve_admin_path(rel_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(str(rel_path))
        data = target.read_bytes()[:max_bytes]
        return {
            "path": rel_path,
            "bytes": len(data),
            "truncated": target.stat().st_size > len(data),
            "content": data.decode("utf-8", errors="replace"),
        }

    def run_allowed_command(self, name: str) -> dict[str, Any]:
        command = self.config.allowed_commands.get(name)
        if not command:
            raise PermissionError(f"Comando no permitido: {name}")
        result = subprocess.run(command, cwd=self._admin_root(), capture_output=True, text=True, timeout=20, check=False)
        return {
            "command": name,
            "argv": command,
            "returncode": result.returncode,
            "stdout": result.stdout[-8000:],
            "stderr": result.stderr[-8000:],
        }

    def _admin_root(self) -> Path:
        return Path(self.config.admin_root).expanduser().resolve()

    def _resolve_admin_path(self, rel_path: str) -> Path:
        root = self._admin_root()
        target = (root / rel_path).resolve()
        if root != target and root not in target.parents:
            raise PermissionError("Ruta fuera de admin_root.")
        return target

    def _worker_loop(self) -> None:
        while True:
            job_id = self.work_queue.get()
            job = self.get_job(job_id)
            if job is None:
                continue
            self._run_job(job)

    def _run_job(self, job: JobRecord) -> None:
        with self.lock:
            job.status = "running"
            job.updated_at = time.time()
            request = (job.result or {}).get("request", {})
        try:
            if job.task == "echo":
                result = {"echo": request.get("payload", {})}
            elif job.task == "sha256":
                text = json.dumps(request.get("payload", {}), sort_keys=True, ensure_ascii=False)
                result = {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "bytes": len(text.encode("utf-8"))}
            else:
                result = self._benchmark(float(request.get("seconds") or 2.0))
            with self.lock:
                job.status = "completed"
                job.result = result
                job.updated_at = time.time()
        except Exception as exc:
            with self.lock:
                job.status = "failed"
                job.error = str(exc)
                job.updated_at = time.time()

    def _benchmark(self, seconds: float) -> dict[str, Any]:
        usage = max(5, min(90, self.config.target_usage_percent)) / 100.0
        window = 0.20
        busy = window * usage
        idle = window - busy
        deadline = time.time() + seconds
        loops = 0
        digest = b"triade"
        while time.time() < deadline:
            busy_until = time.time() + busy
            while time.time() < busy_until:
                digest = hashlib.sha256(digest).digest()
                loops += 1
            if idle > 0:
                time.sleep(idle)
        return {
            "task": "benchmark",
            "target_usage_percent": self.config.target_usage_percent,
            "seconds": seconds,
            "loops": loops,
            "digest": digest.hex()[:24],
        }

    @staticmethod
    def _memory_total_gb() -> float:
        meminfo = Path("/proc/meminfo")
        if not meminfo.exists():
            return 0.0
        for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("MemTotal:"):
                parts = line.split()
                if len(parts) >= 2:
                    return round(int(parts[1]) / 1024 / 1024, 2)
        return 0.0

    @staticmethod
    def _tier(cpu_count: int) -> str:
        ram = MobileNodeAgent._memory_total_gb()
        if cpu_count >= 8 and ram >= 6:
            return "medium"
        return "low"


def load_config(path: Path) -> AgentConfig:
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        return AgentConfig(**data)
    token = os.environ.get("TRIADE_NODE_TOKEN") or secrets.token_urlsafe(24)
    node_id = os.environ.get("TRIADE_NODE_ID", f"mobile-{socket.gethostname()}")
    config = AgentConfig(node_id=node_id, token=token)
    save_config(config, path)
    return config


def save_config(config: AgentConfig, path: Path) -> None:
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")


config = load_config(DEFAULT_STATE_PATH)
agent = MobileNodeAgent(config)
agent.start()
app = FastAPI(title="Triade Mobile Node Agent", version="0.1")


def require_token(authorization: str | None) -> None:
    expected = f"Bearer {agent.config.token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Token invalido.")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "node_id": agent.config.node_id, "mode": "mobile-node-agent"}


@app.get("/capabilities")
def capabilities(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(authorization)
    return agent.capabilities()


@app.get("/config")
def get_config(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(authorization)
    return asdict(agent.config)


@app.post("/config")
def update_config(request: ConfigRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(authorization)
    return asdict(agent.update_config(request))


@app.post("/jobs")
def submit_job(request: JobRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(authorization)
    try:
        return asdict(agent.submit(request))
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/jobs/{job_id}")
def get_job(job_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_token(authorization)
    job = agent.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return asdict(job)


def require_admin(authorization: str | None) -> None:
    require_token(authorization)
    if not agent.config.admin_enabled:
        raise HTTPException(status_code=403, detail="Modo admin desactivado.")


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> str:
    return ADMIN_HTML


@app.get("/admin/files")
def admin_files(path: str = ".", authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    try:
        return agent.list_files(path)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/admin/files/read")
def admin_read_file(path: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    try:
        return agent.read_file(path)
    except (FileNotFoundError, PermissionError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/admin/commands/{name}")
def admin_run_command(name: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    try:
        return agent.run_allowed_command(name)
    except (PermissionError, subprocess.TimeoutExpired, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Tríade Ω mobile node agent")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--token", default=None)
    parser.add_argument("--node-id", default=None)
    parser.add_argument("--usage", type=int, default=None, help="Porcentaje objetivo de uso cooperativo, 5-90")
    parser.add_argument("--admin-root", default=None, help="Carpeta raiz autorizada para lectura web")
    parser.add_argument("--admin-off", action="store_true", help="Desactiva endpoints admin")
    args = parser.parse_args()

    if args.token:
        agent.config.token = args.token
    if args.node_id:
        agent.config.node_id = args.node_id
    if args.usage is not None:
        agent.config.target_usage_percent = max(5, min(90, args.usage))
    if args.admin_root:
        agent.config.admin_root = args.admin_root
        agent.config.admin_enabled = True
    if args.admin_off:
        agent.config.admin_enabled = False
    save_config(agent.config, DEFAULT_STATE_PATH)

    import uvicorn

    uvicorn.run("apps.mobile_node_agent:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()


ADMIN_HTML = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Tríade Ω · Nodo móvil admin</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#101216;color:#f4f6f8}
    main{max-width:860px;margin:0 auto;padding:24px 16px}
    input,button{font:inherit;padding:10px;border-radius:8px;border:1px solid #3a4350;background:#171b22;color:#fff}
    button{background:#61c184;color:#06120a;font-weight:700}
    .row{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}
    pre{white-space:pre-wrap;background:#171b22;border:1px solid #303946;border-radius:8px;padding:12px;overflow:auto}
  </style>
</head>
<body>
<main>
  <h1>Tríade Ω · Admin del nodo móvil</h1>
  <p>Panel consentido. Requiere token Bearer y opera solo dentro de la raíz autorizada.</p>
  <input id="token" placeholder="Token" type="password"/>
  <div class="row">
    <input id="path" value="."/>
    <button onclick="listFiles()">Listar archivos</button>
    <button onclick="readFile()">Leer archivo</button>
  </div>
  <div class="row">
    <button onclick="runCommand('python_version')">Python</button>
    <button onclick="runCommand('whoami')">Whoami</button>
    <button onclick="runCommand('pwd')">PWD</button>
  </div>
  <pre id="out"></pre>
</main>
<script>
function headers(){return {"Authorization":"Bearer "+document.getElementById("token").value}}
function show(x){document.getElementById("out").textContent=typeof x==="string"?x:JSON.stringify(x,null,2)}
async function req(url, opts={}){const r=await fetch(url,{...opts,headers:{...(opts.headers||{}),...headers()}});const j=await r.json();if(!r.ok)throw new Error(JSON.stringify(j));return j}
async function listFiles(){try{show(await req("/admin/files?path="+encodeURIComponent(document.getElementById("path").value)))}catch(e){show(e.message)}}
async function readFile(){try{show(await req("/admin/files/read?path="+encodeURIComponent(document.getElementById("path").value)))}catch(e){show(e.message)}}
async function runCommand(name){try{show(await req("/admin/commands/"+name,{method:"POST"}))}catch(e){show(e.message)}}
</script>
</body>
</html>
"""
