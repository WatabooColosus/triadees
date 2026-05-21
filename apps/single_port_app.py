"""Tríade Ω Single Port App.

Puerto único 8010 para UI, health, router y runs locales.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from triade.core.runner import TriadeRunner
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient

app = FastAPI(title="Tríade Ω Single Port", version="0.1.0")


class RunRequest(BaseModel):
    text: str = Field(..., min_length=1)
    source: str = "single-port-ui"
    use_ollama: bool = False
    hypothalamus_model: str | None = None
    central_model: str | None = None


class RouterRequest(BaseModel):
    intent: str = "conversation"
    urgency: str = "medium"


def require_key(value: str | None) -> None:
    expected = os.getenv("TRIADE_API_KEY")
    if expected and value != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida o ausente.")


def router_payload(intent: str = "conversation", urgency: str = "medium") -> dict[str, Any]:
    hardware = HardwareProfiler().detect()
    ollama = OllamaClient().health()
    router = ModelRouter(available_models=ollama.get("models", []), hardware=hardware)
    return {
        "status": "ok",
        "mode": "single-port",
        "hardware": hardware.to_dict(),
        "ollama": ollama,
        "router": router.route_many(intent=intent, urgency=urgency),
    }


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, Any]:
    runner = TriadeRunner(use_ollama=False)
    hardware = HardwareProfiler().detect()
    ollama = OllamaClient().health()
    return {
        "status": "ok",
        "entity": "Tríade Ω",
        "mode": "single-port",
        "port": 8010,
        "security": {"api_key_required": bool(os.getenv("TRIADE_API_KEY"))},
        "hardware": hardware.to_dict(),
        "ollama": ollama,
        "doctor": runner.doctor(),
    }


@app.post("/api/router/doctor")
def route_doctor(request: RouterRequest) -> dict[str, Any]:
    return router_payload(intent=request.intent, urgency=request.urgency)


@app.post("/api/run")
@app.post("/triade/run")
def run_triade(request: RunRequest, x_triade_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    require_key(x_triade_api_key)
    runner = TriadeRunner(
        use_ollama=request.use_ollama,
        hypothalamus_model=request.hypothalamus_model,
        central_model=request.central_model,
    )
    return runner.run(request.text, source=request.source)


HTML = """
<!doctype html><html lang='es'><head><meta charset='utf-8'/><meta name='viewport' content='width=device-width,initial-scale=1'/>
<title>Tríade Ω Single Port</title>
<style>
body{margin:0;background:#080b10;color:#edf2ff;font-family:Inter,system-ui,sans-serif;padding:18px}.app{max-width:1180px;margin:auto;display:grid;grid-template-columns:330px 1fr;gap:16px}.card{background:#121722;border:1px solid #263246;border-radius:20px}.side{padding:18px}.main{height:calc(100vh - 36px);display:flex;flex-direction:column}label{display:block;color:#9aa7bd;font-size:12px;margin:12px 0 6px}input,select,textarea{width:100%;box-sizing:border-box;background:#171f2e;color:#edf2ff;border:1px solid #263246;border-radius:12px;padding:10px}button{width:100%;margin-top:10px;border:0;border-radius:12px;padding:11px;font-weight:800;background:linear-gradient(135deg,#73c7ff,#9bffb1);color:#061018}.secondary{background:#223047;color:#edf2ff;border:1px solid #263246}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.chat{flex:1;overflow:auto;padding:16px}.msg{padding:13px;border-radius:16px;margin:10px 0;white-space:pre-wrap}.user{background:#1f6feb;margin-left:12%}.bot{background:#171f2e;border:1px solid #263246;margin-right:12%}.meta{font-size:12px;color:#9aa7bd;margin-top:8px}.composer{display:grid;grid-template-columns:1fr 120px;gap:10px;padding:14px;border-top:1px solid #263246}.box{background:#0d121c;border:1px solid #263246;border-radius:12px;padding:10px;margin-top:10px;font-size:12px;white-space:pre-wrap;max-height:260px;overflow:auto}.top{padding:14px;border-bottom:1px solid #263246;color:#9aa7bd}.ok{color:#9bffb1}@media(max-width:850px){.app{grid-template-columns:1fr}.composer{grid-template-columns:1fr}}
</style></head><body><div class='app'><aside class='card side'>
<h2>Tríade Ω</h2><p style='color:#9aa7bd'>Single Port App: UI, health, router, hardware y runs viven en 8010.</p>
<label>API key</label><input id='key' type='password'/><div class='row'><div><label>Intención</label><select id='intent'><option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option></select></div><div><label>Urgencia</label><select id='urgency'><option>medium</option><option>low</option><option>high</option></select></div></div>
<label>Hipotálamo</label><input id='hyp' value='qwen2.5:3b-instruct'/><label>Central</label><input id='cen' value='qwen2.5:3b-instruct'/><label><input id='ollama' type='checkbox'/> Usar Ollama</label>
<button onclick='save()'>Guardar</button><button class='secondary' onclick='health()'>Health 8010</button><button class='secondary' onclick='router()'>Consultar Router</button><button class='secondary' onclick='apply()'>Aplicar recomendados</button><button class='secondary' onclick='clearChat()'>Limpiar</button><div id='box' class='box'>Sin consultar.</div>
</aside><main class='card main'><div class='top'><b>Chat local auditable</b><br><span id='status'>Listo</span></div><section id='chat' class='chat'></section><div class='composer'><textarea id='msg' placeholder='Escribe... Ctrl+Enter' onkeydown='keysend(event)'></textarea><button onclick='send()'>Enviar</button></div></main></div>
<script>
const $=id=>document.getElementById(id);let lastRouter=null;function save(){['key','hyp','cen','intent','urgency'].forEach(k=>localStorage.setItem('triade_sp_'+k,$(k).value));localStorage.setItem('triade_sp_ollama',$('ollama').checked);status('Guardado',true)}function load(){['key','hyp','cen','intent','urgency'].forEach(k=>{const v=localStorage.getItem('triade_sp_'+k);if(v)$(k).value=v});$('ollama').checked=localStorage.getItem('triade_sp_ollama')==='true'}function status(t,ok=false){$('status').textContent=t;$('status').className=ok?'ok':''}function add(cls,text,meta=''){let d=document.createElement('div');d.className='msg '+cls;d.textContent=text;if(meta){let m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}$('chat').appendChild(d);$('chat').scrollTop=$('chat').scrollHeight}
async function health(){try{let r=await fetch('/api/health');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({mode:j.mode,hardware:j.hardware,ollama:j.ollama?.ok,models:j.ollama?.models,runs:j.doctor?.counts?.runs},null,2);status('Health OK',true)}catch(e){status('Health falló: '+e.message)}}
async function router(){try{let r=await fetch('/api/router/doctor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intent:$('intent').value,urgency:$('urgency').value})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);lastRouter=j;let d=j.router.decisions;$('box').textContent=JSON.stringify({hardware:j.hardware,central:d.central?.selected_model,hypothalamus:d.hypothalamus?.selected_model,fast:d.fast?.selected_model,deep:d.deep?.selected_model,rejected:d.central?.rejected_by_hardware},null,2);status('Router OK',true)}catch(e){status('Router falló: '+e.message)}}
function apply(){if(!lastRouter){status('Consulta router primero');return}let d=lastRouter.router.decisions;if(d.hypothalamus?.selected_model)$('hyp').value=d.hypothalamus.selected_model;if(d.central?.selected_model)$('cen').value=d.central.selected_model;$('ollama').checked=true;save();status('Recomendados aplicados',true)}
async function send(){save();let text=$('msg').value.trim();if(!text)return;$('msg').value='';add('user',text);status('Procesando...');try{let r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':$('key').value},body:JSON.stringify({text,source:'single-port-ui',use_ollama:$('ollama').checked,hypothalamus_model:$('hyp').value,central_model:$('cen').value})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);add('bot',j.response,[j.run_id,j.run_path,'H '+j.models?.hypothalamus?.name,'C '+j.models?.central?.name].filter(Boolean).join(' · '));status('Respuesta recibida',true)}catch(e){add('bot','Error: '+e.message);status('Error')}}function clearChat(){$('chat').innerHTML=''}function keysend(e){if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))send()}load();add('bot','Tríade Ω Single Port lista. Todo corre por 8010.');
</script></body></html>
"""


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    return HTML
