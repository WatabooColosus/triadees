"""Interfaz web local unificada para Tríade Ω.

DEPRECATED_UI: Migrated to single_port_app.py. Keep until v2.4.

La UI vive en http://127.0.0.1:8010 y usa proxy interno para hablar con:
- Tríade API: http://127.0.0.1:8000
- Model Router: http://127.0.0.1:8020

Así el navegador no necesita CORS entre puertos.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Tríade Ω Chat UI", version="0.3.0")

TRIADE_API_BASE = "http://127.0.0.1:8000"
MODEL_ROUTER_BASE = "http://127.0.0.1:8010"


class ChatProxyRequest(BaseModel):
    text: str = Field(..., min_length=1)
    use_ollama: bool = False
    hypothalamus_model: str | None = None
    central_model: str | None = None
    source: str = "chat-ui-unified"


class RouterProxyRequest(BaseModel):
    intent: str = "conversation"
    urgency: str = "medium"


def _request_json(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=exc.code, detail=detail) from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@app.get("/api/health")
def proxy_health() -> dict[str, Any]:
    return _request_json(f"{TRIADE_API_BASE}/health", timeout=15)


@app.post("/api/run")
def proxy_run(request: ChatProxyRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    headers = {"X-TRIADE-API-Key": x_triade_api_key or ""}
    payload = {
        "text": request.text,
        "source": request.source,
        "use_ollama": request.use_ollama,
        "hypothalamus_model": request.hypothalamus_model,
        "central_model": request.central_model,
    }
    return _request_json(f"{TRIADE_API_BASE}/triade/run", method="POST", payload=payload, headers=headers)


@app.post("/api/router/doctor")
def proxy_router_doctor(request: RouterProxyRequest) -> dict[str, Any]:
    query = urllib.parse.urlencode({"intent": request.intent, "urgency": request.urgency})
    return _request_json(f"{MODEL_ROUTER_BASE}/api/models/doctor?{query}", timeout=20)


HTML = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tríade Ω · Chat Local</title>
  <style>
    :root{--bg:#090b10;--panel:#121722;--panel2:#171f2e;--text:#edf2ff;--muted:#9aa7bd;--accent:#8fd3ff;--ok:#9bffb1;--warn:#ffd88f;--border:#263246}
    *{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at top left,#172033 0,#090b10 42%,#06070a 100%);color:var(--text);font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh;display:flex;justify-content:center;padding:18px}
    .app{width:min(1180px,100%);display:grid;grid-template-columns:330px 1fr;gap:16px}.card{background:rgba(18,23,34,.94);border:1px solid var(--border);border-radius:22px;box-shadow:0 20px 70px rgba(0,0,0,.35)}
    .side{padding:18px;height:calc(100vh - 36px);overflow:auto}.main{display:flex;flex-direction:column;height:calc(100vh - 36px);overflow:hidden}.brand{font-size:24px;font-weight:850;margin-bottom:6px}.subtitle,.small,.status{color:var(--muted);font-size:13px;line-height:1.42}.ok{color:var(--ok)}
    label{display:block;color:var(--muted);font-size:12px;margin:13px 0 6px}input,textarea,select{width:100%;background:var(--panel2);border:1px solid var(--border);color:var(--text);border-radius:12px;padding:10px 11px;outline:none}input:focus,textarea:focus{border-color:var(--accent)}textarea{resize:none}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.check{display:flex;gap:8px;align-items:center;margin-top:10px}.check input{width:auto}
    button{width:100%;border:0;border-radius:14px;padding:11px 12px;margin-top:10px;background:linear-gradient(135deg,#73c7ff,#9bffb1);color:#061018;font-weight:850;cursor:pointer}.secondary{background:#223047;color:var(--text);border:1px solid var(--border)}
    .routerBox{background:#0d121c;border:1px solid var(--border);border-radius:14px;padding:10px;margin-top:10px;font-size:12px;color:#cbd6ea;white-space:pre-wrap;max-height:230px;overflow:auto}.topbar{padding:15px 17px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;gap:12px;align-items:center}.chat{flex:1;overflow:auto;padding:17px;display:flex;flex-direction:column;gap:13px}.msg{max-width:86%;padding:14px 15px;border-radius:18px;line-height:1.48;white-space:pre-wrap}.user{align-self:flex-end;background:#1f6feb}.bot{align-self:flex-start;background:var(--panel2);border:1px solid var(--border)}.meta{color:var(--muted);font-size:12px;margin-top:8px;border-top:1px solid rgba(255,255,255,.08);padding-top:7px}.composer{padding:15px;border-top:1px solid var(--border);display:grid;grid-template-columns:1fr 125px;gap:10px}.composer textarea{min-height:52px;max-height:140px}.composer button{height:52px;margin:0}
    @media(max-width:850px){body{padding:10px}.app{grid-template-columns:1fr}.side{height:auto}.main{height:72vh}.composer{grid-template-columns:1fr}.composer button{height:auto}}
  </style>
</head>
<body>
<div class="app">
  <aside class="card side">
    <div class="brand">Tríade Ω</div>
    <div class="subtitle">Chat local unificado. El navegador solo habla con el puerto 8010; la UI hace proxy interno hacia Tríade API y Model Router.</div>

    <label>API key local</label><input id="apiKey" type="password" placeholder="X-TRIADE-API-Key" />
    <div class="row"><div><label>Intención</label><select id="intent"><option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option></select></div><div><label>Urgencia</label><select id="urgency"><option>medium</option><option>low</option><option>high</option></select></div></div>
    <label>Modelo Hipotálamo</label><input id="hypModel" value="qwen2.5:3b-instruct" />
    <label>Modelo Central</label><input id="cenModel" value="qwen2.5:3b-instruct" />
    <label class="check"><input id="useOllama" type="checkbox" /> Usar Ollama</label>

    <button onclick="saveSettings()">Guardar ajustes</button>
    <button class="secondary" onclick="checkHealth()">Health Tríade</button>
    <button class="secondary" onclick="checkRouter()">Consultar Model Router</button>
    <button class="secondary" onclick="applyRouter()">Aplicar recomendados</button>
    <button class="secondary" onclick="clearChat()">Limpiar chat</button>
    <div id="routerBox" class="routerBox">Router sin consultar.</div>
    <div class="small">Endpoints internos: /api/health · /api/router/doctor · /api/run. La API real sigue en /triade/run detrás del proxy.</div>
  </aside>

  <main class="card main">
    <div class="topbar"><div><strong>Chat local auditable</strong><br><span id="status" class="status">Listo.</span></div><span id="lastRun" class="status">sin run</span></div>
    <section id="chat" class="chat"></section>
    <div class="composer"><textarea id="message" placeholder="Escribe a Tríade... Ctrl+Enter envía" onkeydown="handleKey(event)"></textarea><button onclick="sendMessage()">Enviar</button></div>
  </main>
</div>
<script>
const els={apiKey:q('apiKey'),hypModel:q('hypModel'),cenModel:q('cenModel'),useOllama:q('useOllama'),intent:q('intent'),urgency:q('urgency'),routerBox:q('routerBox'),status:q('status'),lastRun:q('lastRun'),chat:q('chat'),message:q('message')};let routerPayload=null;function q(id){return document.getElementById(id)}
function load(){for(const k of ['apiKey','hypModel','cenModel','intent','urgency']){const v=localStorage.getItem('triade_unified_'+k);if(v&&els[k])els[k].value=v}els.useOllama.checked=localStorage.getItem('triade_unified_useOllama')==='true'}
function saveSettings(){for(const k of ['apiKey','hypModel','cenModel','intent','urgency'])localStorage.setItem('triade_unified_'+k,els[k].value.trim());localStorage.setItem('triade_unified_useOllama',String(els.useOllama.checked));setStatus('Ajustes guardados.',true)}
function setStatus(t,ok=false){els.status.textContent=t;els.status.className=ok?'status ok':'status'}
function add(role,text,meta=''){const d=document.createElement('div');d.className='msg '+(role==='user'?'user':'bot');d.textContent=text;if(meta){const m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}els.chat.appendChild(d);els.chat.scrollTop=els.chat.scrollHeight}
async function checkHealth(){saveSettings();try{const r=await fetch('/api/health');const j=await r.json();if(!r.ok)throw new Error(j.detail||'HTTP '+r.status);setStatus('Health '+j.status+' · runs='+(j.doctor?.counts?.runs??'?'),true)}catch(e){setStatus('Health falló: '+e.message)}}
async function checkRouter(){saveSettings();try{const r=await fetch('/api/router/doctor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intent:els.intent.value,urgency:els.urgency.value})});const j=await r.json();if(!r.ok)throw new Error(j.detail||'HTTP '+r.status);routerPayload=j;const d=j.router?.decisions||{};els.routerBox.textContent=JSON.stringify({ollama:j.ollama?.ok,central:d.central?.selected_model,hypothalamus:d.hypothalamus?.selected_model,coder:d.coder?.selected_model,embedding:d.embedding?.selected_model,fast:d.fast?.selected_model,deep:d.deep?.selected_model},null,2);setStatus('Router consultado.',true)}catch(e){els.routerBox.textContent='Error router: '+e.message;setStatus('Router falló')}}
function applyRouter(){if(!routerPayload){setStatus('Primero consulta el router.');return}const d=routerPayload.router?.decisions||{};if(d.hypothalamus?.selected_model)els.hypModel.value=d.hypothalamus.selected_model;if(d.central?.selected_model)els.cenModel.value=d.central.selected_model;els.useOllama.checked=true;saveSettings();setStatus('Modelos recomendados aplicados.',true)}
async function sendMessage(){saveSettings();const text=els.message.value.trim();if(!text)return;els.message.value='';add('user',text);setStatus('Procesando...');const payload={text,source:'chat-ui-unified',use_ollama:els.useOllama.checked,hypothalamus_model:els.hypModel.value.trim()||null,central_model:els.cenModel.value.trim()||null};try{const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':els.apiKey.value.trim()},body:JSON.stringify(payload)});const j=await r.json();if(!r.ok)throw new Error(j.detail||'HTTP '+r.status);els.lastRun.textContent=j.run_id||'run';const h=j.models?.hypothalamus,c=j.models?.central;add('bot',j.response||'(sin respuesta)',[j.run_id?'run: '+j.run_id:'',j.run_path?'path: '+j.run_path:'',h?'H: '+h.name+' ok='+h.ok:'',c?'C: '+c.name+' ok='+c.ok:''].filter(Boolean).join(' · '));setStatus('Respuesta recibida.',true)}catch(e){add('bot','Error: '+e.message);setStatus('Error al enviar')}}
function handleKey(e){if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))sendMessage()}function clearChat(){els.chat.innerHTML='';els.lastRun.textContent='sin run';setStatus('Chat limpiado.',true)}
load();add('bot','Tríade Ω unificada lista. Usa Health, consulta el Router y aplica modelos recomendados.');
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    return HTML
