"""Chat UI local con integración de Model Router."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Tríade Ω Chat UI + Model Router", version="0.2.0")

HTML = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tríade Ω · Chat + Router</title>
  <style>
    body{margin:0;background:#080b10;color:#edf2ff;font-family:Inter,system-ui,sans-serif;padding:18px}
    .app{max-width:1180px;margin:auto;display:grid;grid-template-columns:330px 1fr;gap:16px}
    .card{background:#121722;border:1px solid #263246;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.35)}
    .side{padding:18px;height:calc(100vh - 36px);overflow:auto}.main{height:calc(100vh - 36px);display:flex;flex-direction:column;overflow:hidden}
    h1{font-size:24px;margin:0 0 6px}.muted{color:#9aa7bd;font-size:13px;line-height:1.45}
    label{display:block;color:#9aa7bd;font-size:12px;margin:13px 0 6px} input,textarea,select{width:100%;box-sizing:border-box;background:#171f2e;color:#edf2ff;border:1px solid #263246;border-radius:12px;padding:10px;outline:none} textarea{resize:none}
    input:focus,textarea:focus{border-color:#8fd3ff} button{width:100%;border:0;border-radius:13px;padding:11px 12px;margin-top:10px;background:linear-gradient(135deg,#73c7ff,#9bffb1);color:#061018;font-weight:800;cursor:pointer}.secondary{background:#223047;color:#edf2ff;border:1px solid #263246}.mini{font-size:12px;padding:8px 10px;margin-top:7px}
    .row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.check{display:flex;gap:8px;align-items:center;margin-top:10px;color:#9aa7bd;font-size:13px}.check input{width:auto}
    .top{padding:14px 16px;border-bottom:1px solid #263246;display:flex;justify-content:space-between;gap:12px}.status{color:#9aa7bd;font-size:13px}.ok{color:#9bffb1}.warn{color:#ffd88f}
    .chat{flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:12px}.msg{max-width:86%;padding:13px 14px;border-radius:17px;line-height:1.45;white-space:pre-wrap}.user{align-self:flex-end;background:#1f6feb}.bot{align-self:flex-start;background:#171f2e;border:1px solid #263246}.meta{color:#9aa7bd;font-size:12px;margin-top:8px;border-top:1px solid rgba(255,255,255,.08);padding-top:7px}
    .composer{padding:14px;border-top:1px solid #263246;display:grid;grid-template-columns:1fr 120px;gap:10px}.composer button{height:52px;margin:0}.routerBox{background:#0d121c;border:1px solid #263246;border-radius:14px;padding:10px;margin-top:10px;font-size:12px;color:#cbd6ea;white-space:pre-wrap;max-height:220px;overflow:auto}
    @media(max-width:850px){.app{grid-template-columns:1fr}.side{height:auto}.main{height:72vh}.composer{grid-template-columns:1fr}}
  </style>
</head>
<body>
<div class="app">
  <aside class="card side">
    <h1>Tríade Ω</h1>
    <div class="muted">Chat local con Model Router. Recomienda modelos por rol y permite aplicarlos antes de enviar.</div>

    <label>API Tríade</label><input id="apiBase" value="http://127.0.0.1:8000" />
    <label>API key</label><input id="apiKey" type="password" placeholder="X-TRIADE-API-Key" />
    <label>Model Router (unificado en 8010)</label><input id="routerBase" value="http://127.0.0.1:8010" />

    <div class="row">
      <div><label>Intención router</label><select id="intent"><option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option></select></div>
      <div><label>Urgencia</label><select id="urgency"><option>medium</option><option>low</option><option>high</option></select></div>
    </div>

    <label>Modelo Hipotálamo</label><input id="hypModel" value="qwen2.5:3b-instruct" />
    <label>Modelo Central</label><input id="cenModel" value="qwen2.5:3b-instruct" />
    <label class="check"><input id="useOllama" type="checkbox" /> Usar Ollama</label>

    <button onclick="saveSettings()">Guardar ajustes</button>
    <button class="secondary" onclick="checkHealth()">Health Tríade</button>
    <button class="secondary" onclick="checkRouter()">Consultar Model Router</button>
    <button class="secondary" onclick="applyRouter()">Aplicar recomendados</button>
    <button class="secondary" onclick="clearChat()">Limpiar chat</button>

    <div id="routerBox" class="routerBox">Router sin consultar.</div>
  </aside>

  <main class="card main">
    <div class="top"><div><b>Chat local auditable</b><br><span id="status" class="status">Listo.</span></div><span id="lastRun" class="status">sin run</span></div>
    <section id="chat" class="chat"></section>
    <div class="composer"><textarea id="message" placeholder="Escribe a Tríade... Ctrl+Enter envía" onkeydown="handleKey(event)"></textarea><button onclick="sendMessage()">Enviar</button></div>
  </main>
</div>
<script>
const els={apiBase:q('apiBase'),apiKey:q('apiKey'),routerBase:q('routerBase'),hypModel:q('hypModel'),cenModel:q('cenModel'),useOllama:q('useOllama'),intent:q('intent'),urgency:q('urgency'),routerBox:q('routerBox'),status:q('status'),lastRun:q('lastRun'),chat:q('chat'),message:q('message')};
let routerPayload=null; function q(id){return document.getElementById(id)}
function load(){for(const k of ['apiBase','apiKey','routerBase','hypModel','cenModel','intent','urgency']){const v=localStorage.getItem('triade_'+k); if(v&&els[k]) els[k].value=v} els.useOllama.checked=localStorage.getItem('triade_useOllama')==='true'}
function saveSettings(){for(const k of ['apiBase','apiKey','routerBase','hypModel','cenModel','intent','urgency']) localStorage.setItem('triade_'+k,els[k].value.trim()); localStorage.setItem('triade_useOllama',String(els.useOllama.checked)); setStatus('Ajustes guardados.',true)}
function setStatus(t,ok=false){els.status.textContent=t;els.status.className=ok?'status ok':'status'}
function add(role,text,meta=''){const d=document.createElement('div');d.className='msg '+(role==='user'?'user':'bot');d.textContent=text;if(meta){const m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}els.chat.appendChild(d);els.chat.scrollTop=els.chat.scrollHeight}
async function checkHealth(){saveSettings();try{const r=await fetch(els.apiBase.value+'/health');const j=await r.json();setStatus('Tríade health '+j.status+' · runs='+(j.doctor?.counts?.runs??'?'),r.ok)}catch(e){setStatus('Health falló: '+e.message)}}
async function checkRouter(){saveSettings();try{const url=els.routerBase.value+`/models/doctor?intent=${encodeURIComponent(els.intent.value)}&urgency=${encodeURIComponent(els.urgency.value)}`;const r=await fetch(url);const j=await r.json();routerPayload=j;const d=j.router?.decisions||{};els.routerBox.textContent=JSON.stringify({ollama:j.ollama?.ok,central:d.central?.selected_model,hypothalamus:d.hypothalamus?.selected_model,coder:d.coder?.selected_model,embedding:d.embedding?.selected_model,fast:d.fast?.selected_model,deep:d.deep?.selected_model},null,2);setStatus('Router consultado.',true)}catch(e){els.routerBox.textContent='Error router: '+e.message;setStatus('Router falló')}}
function applyRouter(){if(!routerPayload){setStatus('Primero consulta el router.');return}const d=routerPayload.router?.decisions||{};if(d.hypothalamus?.selected_model) els.hypModel.value=d.hypothalamus.selected_model;if(d.central?.selected_model) els.cenModel.value=d.central.selected_model;els.useOllama.checked=true;saveSettings();setStatus('Modelos recomendados aplicados.',true)}
async function sendMessage(){saveSettings();const text=els.message.value.trim();if(!text)return;els.message.value='';add('user',text);setStatus('Procesando...');const payload={text,source:'chat-ui-router-local',use_ollama:els.useOllama.checked,hypothalamus_model:els.hypModel.value.trim()||null,central_model:els.cenModel.value.trim()||null};try{const r=await fetch(els.apiBase.value+'/triade/run',{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':els.apiKey.value.trim()},body:JSON.stringify(payload)});const j=await r.json();if(!r.ok)throw new Error(j.detail||'HTTP '+r.status);els.lastRun.textContent=j.run_id||'run';const h=j.models?.hypothalamus,c=j.models?.central;add('bot',j.response||'(sin respuesta)',[j.run_id?'run: '+j.run_id:'',j.run_path?'path: '+j.run_path:'',h?'H: '+h.name+' ok='+h.ok:'',c?'C: '+c.name+' ok='+c.ok:''].filter(Boolean).join(' · '));setStatus('Respuesta recibida.',true)}catch(e){add('bot','Error: '+e.message);setStatus('Error al enviar')}}
function handleKey(e){if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))sendMessage()} function clearChat(){els.chat.innerHTML='';els.lastRun.textContent='sin run';setStatus('Chat limpiado.',true)}
load();add('bot','Tríade Ω lista con Model Router. Pulsa “Consultar Model Router” para ver recomendaciones.');
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
