"""Relay publico para nodos Tríade conectados por navegador.

Los dispositivos se conectan hacia afuera a esta web. Esto evita depender de
puertos abiertos en celulares, CGNAT o Ubuntu/Termux pesado.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


DB_PATH = Path(os.environ.get("TRIADE_RELAY_DB", "triade/memory/public_relay.db"))
PAIRING_TOKEN = os.environ.get("TRIADE_RELAY_PAIRING_TOKEN", "triade-public-pair")
ADMIN_TOKEN = os.environ.get("TRIADE_RELAY_ADMIN_TOKEN", "triade-public-admin")

app = FastAPI(title="Triade Public Relay", version="0.1")


class RegisterRequest(BaseModel):
    pairing_token: str = Field(..., min_length=1)
    display_name: str = Field(default="Dispositivo navegador", min_length=1, max_length=80)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class HeartbeatRequest(BaseModel):
    node_id: str
    node_token: str
    capabilities: dict[str, Any] = Field(default_factory=dict)


class JobRequest(BaseModel):
    node_id: str
    task: str = Field(..., pattern="^(echo|sha256|browser_benchmark)$")
    payload: dict[str, Any] = Field(default_factory=dict)
    seconds: float = Field(default=2.0, ge=0.1, le=20.0)


class JobResultRequest(BaseModel):
    node_id: str
    node_token: str
    status: str = Field(..., pattern="^(completed|failed)$")
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS relay_nodes (
            node_id TEXT PRIMARY KEY,
            node_token TEXT NOT NULL,
            display_name TEXT NOT NULL,
            capabilities TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at REAL NOT NULL,
            last_seen_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS relay_jobs (
            job_id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL,
            task TEXT NOT NULL,
            payload TEXT NOT NULL,
            seconds REAL DEFAULT 2.0,
            status TEXT DEFAULT 'queued',
            result TEXT,
            error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        """
    )
    return conn


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "mode": "public-relay", "pairing_enabled": True}


@app.get("/", response_class=HTMLResponse)
def index(token: str = "") -> str:
    return HTML.replace("__TOKEN__", _escape(token))


@app.post("/api/register")
def register(request: RegisterRequest) -> dict[str, Any]:
    if request.pairing_token != PAIRING_TOKEN:
        raise HTTPException(status_code=401, detail="Token de emparejamiento invalido.")
    node_id = f"web-{uuid4().hex[:10]}"
    node_token = uuid4().hex
    now = time.time()
    capabilities = _normalize_capabilities(request.capabilities)
    with connect() as conn:
        conn.execute(
            """INSERT INTO relay_nodes
            (node_id, node_token, display_name, capabilities, status, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (node_id, node_token, request.display_name.strip(), json.dumps(capabilities, ensure_ascii=False), now, now),
        )
    return {"status": "ok", "node_id": node_id, "node_token": node_token, "capabilities": capabilities}


@app.post("/api/heartbeat")
def heartbeat(request: HeartbeatRequest) -> dict[str, Any]:
    node = _require_node(request.node_id, request.node_token)
    capabilities = _normalize_capabilities(request.capabilities or json.loads(node["capabilities"]))
    with connect() as conn:
        conn.execute(
            "UPDATE relay_nodes SET capabilities = ?, last_seen_at = ?, status = 'active' WHERE node_id = ?",
            (json.dumps(capabilities, ensure_ascii=False), time.time(), request.node_id),
        )
    return {"status": "ok", "node_id": request.node_id, "server_time": time.time()}


@app.get("/api/nodes")
def list_nodes(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM relay_nodes ORDER BY last_seen_at DESC").fetchall()
    return {"status": "ok", "nodes": [_decode_node(row) for row in rows]}


@app.post("/api/jobs")
def create_job(request: JobRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    with connect() as conn:
        exists = conn.execute("SELECT node_id FROM relay_nodes WHERE node_id = ?", (request.node_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Nodo no encontrado.")
        job_id = f"rjob-{uuid4().hex[:12]}"
        now = time.time()
        conn.execute(
            """INSERT INTO relay_jobs
            (job_id, node_id, task, payload, seconds, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)""",
            (job_id, request.node_id, request.task, json.dumps(request.payload, ensure_ascii=False), request.seconds, now, now),
        )
    return {"status": "ok", "job_id": job_id}


@app.get("/api/jobs/next")
def next_job(node_id: str, node_token: str) -> dict[str, Any]:
    _require_node(node_id, node_token)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM relay_jobs WHERE node_id = ? AND status = 'queued' ORDER BY created_at LIMIT 1",
            (node_id,),
        ).fetchone()
        if row is None:
            return {"status": "idle"}
        conn.execute("UPDATE relay_jobs SET status = 'running', updated_at = ? WHERE job_id = ?", (time.time(), row["job_id"]))
    payload = dict(row)
    payload["payload"] = json.loads(payload["payload"] or "{}")
    return {"status": "ok", "job": payload}


@app.post("/api/jobs/{job_id}/result")
def submit_result(job_id: str, request: JobResultRequest) -> dict[str, Any]:
    _require_node(request.node_id, request.node_token)
    with connect() as conn:
        row = conn.execute("SELECT * FROM relay_jobs WHERE job_id = ? AND node_id = ?", (job_id, request.node_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Job no encontrado.")
        conn.execute(
            "UPDATE relay_jobs SET status = ?, result = ?, error = ?, updated_at = ? WHERE job_id = ?",
            (request.status, json.dumps(request.result, ensure_ascii=False), request.error, time.time(), job_id),
        )
    return {"status": "ok", "job_id": job_id}


@app.get("/api/jobs")
def list_jobs(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin(authorization)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM relay_jobs ORDER BY created_at DESC LIMIT 100").fetchall()
    jobs = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item["payload"] or "{}")
        item["result"] = json.loads(item["result"] or "null")
        jobs.append(item)
    return {"status": "ok", "jobs": jobs}


def require_admin(authorization: str | None) -> None:
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Token admin invalido.")


def _require_node(node_id: str, node_token: str) -> sqlite3.Row:
    with connect() as conn:
        row = conn.execute("SELECT * FROM relay_nodes WHERE node_id = ?", (node_id,)).fetchone()
    if row is None or row["node_token"] != node_token:
        raise HTTPException(status_code=401, detail="Nodo o token invalido.")
    return row


def _decode_node(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["capabilities"] = json.loads(item["capabilities"] or "{}")
    item["online"] = (time.time() - float(item["last_seen_at"])) < 45
    return item


def _normalize_capabilities(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "tier": "browser",
        "browser_node": True,
        "cpu_count": int(payload.get("hardware_concurrency") or 1),
        "device_memory_gb": float(payload.get("device_memory_gb") or 0.0),
        "platform": str(payload.get("platform") or "unknown")[:120],
        "user_agent": str(payload.get("user_agent") or "unknown")[:300],
        "screen": payload.get("screen") if isinstance(payload.get("screen"), dict) else {},
        "public_relay": True,
        "background_execution": False,
    }


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


HTML = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Tríade Ω · Nodo Web Público</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#101216;color:#f4f6f8}
    main{max-width:720px;margin:0 auto;padding:28px 18px}
    input,button{font:inherit;box-sizing:border-box;width:100%;padding:12px;border-radius:8px;border:1px solid #34404d;background:#171b22;color:#fff;margin:6px 0}
    button{background:#61c184;color:#07130c;font-weight:800;border:0}
    pre{white-space:pre-wrap;background:#171b22;border:1px solid #303946;border-radius:8px;padding:12px;overflow:auto}
    .ok{color:#81e99f}.bad{color:#ff8b8b}
  </style>
</head>
<body>
<main>
  <h1>Tríade Ω · Nodo web público</h1>
  <p>Este dispositivo se conecta a la web pública y puede ejecutar trabajos ligeros de navegador mientras esta página permanezca abierta.</p>
  <input id="name" value="Dispositivo web"/>
  <input id="token" value="__TOKEN__" placeholder="Token de emparejamiento"/>
  <button onclick="registerNode()">Conectar dispositivo</button>
  <button onclick="stopLoop()">Pausar trabajos</button>
  <p id="status">Sin conectar.</p>
  <pre id="out"></pre>
</main>
<script>
let nodeId="", nodeToken="", running=false;
function caps(){return {hardware_concurrency:navigator.hardwareConcurrency||1,device_memory_gb:navigator.deviceMemory||0,platform:navigator.platform,user_agent:navigator.userAgent,screen:{width:screen.width,height:screen.height,pixel_ratio:devicePixelRatio||1}}}
function show(x){document.getElementById("out").textContent=typeof x==="string"?x:JSON.stringify(x,null,2)}
async function registerNode(){
  const r=await fetch("/api/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({pairing_token:document.getElementById("token").value.trim(),display_name:document.getElementById("name").value.trim()||"Dispositivo web",capabilities:caps()})});
  const j=await r.json(); if(!r.ok){document.getElementById("status").textContent=JSON.stringify(j);return}
  nodeId=j.node_id; nodeToken=j.node_token; running=true; document.getElementById("status").textContent="Conectado: "+nodeId; show(j); loop();
}
function stopLoop(){running=false;document.getElementById("status").textContent="Pausado."}
async function loop(){
  while(running){
    try{
      await fetch("/api/heartbeat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({node_id:nodeId,node_token:nodeToken,capabilities:caps()})});
      const r=await fetch(`/api/jobs/next?node_id=${encodeURIComponent(nodeId)}&node_token=${encodeURIComponent(nodeToken)}`);
      const j=await r.json();
      if(j.status==="ok") await runJob(j.job);
    }catch(e){show("Error: "+e.message)}
    await new Promise(resolve=>setTimeout(resolve,3000));
  }
}
async function runJob(job){
  let result={};
  try{
    if(job.task==="echo") result={echo:job.payload};
    else if(job.task==="sha256") result=await sha256(JSON.stringify(job.payload||{}));
    else result=benchmark(job.seconds||2);
    await fetch(`/api/jobs/${job.job_id}/result`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({node_id:nodeId,node_token:nodeToken,status:"completed",result})});
  }catch(e){
    await fetch(`/api/jobs/${job.job_id}/result`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({node_id:nodeId,node_token:nodeToken,status:"failed",error:e.message})});
  }
}
async function sha256(text){const data=new TextEncoder().encode(text);const hash=await crypto.subtle.digest("SHA-256",data);return {sha256:[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,"0")).join(""),bytes:data.length}}
function benchmark(seconds){const end=performance.now()+seconds*1000;let loops=0,x=1;while(performance.now()<end){x=(x*1664525+1013904223)>>>0;loops++}return {task:"browser_benchmark",seconds,loops,score:Math.round(loops/seconds),seed:x}}
</script>
</body>
</html>
"""
