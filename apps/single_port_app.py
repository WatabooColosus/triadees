"""Tríade Ω Single Port App.

Puerto único 8010 para UI, health, router, compatibilidad, memoria semántica y runs locales.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from triade.core.runner import TriadeRunner
from triade.memory.semantic_embedding_engine import SemanticEmbeddingEngine
from triade.memory.semantic_governance import SemanticMemoryGovernance
from triade.memory.semantic_search import SemanticSearchEngine
from triade.models.compatibility_matrix import ModelCompatibilityMatrix
from triade.models.hardware_profile import HardwareProfiler
from triade.models.model_install_queue import ModelInstallQueue
from triade.models.model_router import ModelRouter
from triade.models.ollama_client import OllamaClient

app = FastAPI(title="Tríade Ω Single Port", version="0.9.1")


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


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, Any]:
    runner = TriadeRunner(use_ollama=False)
    hardware, ollama = system_payload()
    return {
        "status": "ok", "entity": "Tríade Ω", "mode": "single-port", "port": 8010,
        "security": {"api_key_required": bool(os.getenv("TRIADE_API_KEY"))},
        "hardware": hardware.to_dict(), "ollama": ollama, "doctor": runner.doctor(),
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
body{margin:0;background:#080b10;color:#edf2ff;font-family:Inter,system-ui,sans-serif;padding:18px}.app{max-width:1180px;margin:auto;display:grid;grid-template-columns:350px 1fr;gap:16px}.card{background:#121722;border:1px solid #263246;border-radius:20px}.side{padding:18px;overflow:auto;max-height:calc(100vh - 36px)}.main{height:calc(100vh - 36px);display:flex;flex-direction:column}label{display:block;color:#9aa7bd;font-size:12px;margin:12px 0 6px}input,select,textarea{width:100%;box-sizing:border-box;background:#171f2e;color:#edf2ff;border:1px solid #263246;border-radius:12px;padding:10px}button{width:100%;margin-top:10px;border:0;border-radius:12px;padding:11px;font-weight:800;background:linear-gradient(135deg,#73c7ff,#9bffb1);color:#061018}.secondary{background:#223047;color:#edf2ff;border:1px solid #263246}.row{display:grid;grid-template-columns:1fr 1fr;gap:8px}.chat{flex:1;overflow:auto;padding:16px}.msg{padding:13px;border-radius:16px;margin:10px 0;white-space:pre-wrap}.user{background:#1f6feb;margin-left:12%}.bot{background:#171f2e;border:1px solid #263246;margin-right:12%}.event{background:#211a07;border:1px solid #f0b84a;color:#fff2cc;margin-right:6%;margin-left:6%}.event.warning{background:#281111;border-color:#ff7b72;color:#ffd8d5}.event.important{background:#18142a;border-color:#b6a0ff;color:#eee7ff}.event.info{background:#0c1f1a;border-color:#56d39a;color:#dfffee}.meta{font-size:12px;color:#9aa7bd;margin-top:8px}.composer{display:grid;grid-template-columns:1fr 120px;gap:10px;padding:14px;border-top:1px solid #263246}.box{background:#0d121c;border:1px solid #263246;border-radius:12px;padding:10px;margin-top:10px;font-size:12px;white-space:pre-wrap;max-height:260px;overflow:auto}.top{padding:14px;border-bottom:1px solid #263246;color:#9aa7bd}.ok{color:#9bffb1}.hint{font-size:11px;color:#8292ad;margin-top:4px}@media(max-width:850px){.app{grid-template-columns:1fr}.composer{grid-template-columns:1fr}}
</style></head><body><div class='app'><aside class='card side'>
<h2>Tríade Ω</h2><p style='color:#9aa7bd'>Single Port App: conversación, modelos, Cristal y memoria semántica en 8010.</p>
<label>API key</label><input id='key' type='password'/><div class='row'><div><label>Intención router</label><select id='intent'><option>conversation</option><option>analyze</option><option>memory</option><option>build_or_update</option></select></div><div><label>Urgencia</label><select id='urgency'><option>medium</option><option>low</option><option>high</option></select></div></div>
<label>Hipotálamo (vacío = automático)</label><input id='hyp' value=''/><label>Central (vacío = automático)</label><input id='cen' value=''/><label><input id='ollama' type='checkbox'/> Usar Ollama</label><label><input id='auto' type='checkbox' checked/> Auto elegir modelos</label>
<hr style='border-color:#263246;margin:16px 0'/><b style='font-size:13px'>Contexto del Cristal</b><div class='hint'>Evita comparar runs de proyectos o neuronas diferentes.</div>
<label>Proyecto (opcional)</label><input id='project' placeholder='triade-local, xiaos, elestial...'/><label>Neurona activa (opcional)</label><input id='neuron' placeholder='cristal, xiaos, bodega...'/><label>Sesión (opcional)</label><input id='session' placeholder='sesion-prueba-01'/><label>Scope</label><select id='scope'><option value=''>Automático</option><option value='source_intent'>Source + intent</option><option value='session'>Sesión</option><option value='project'>Proyecto</option><option value='neuron'>Neurona</option><option value='project_neuron'>Proyecto + neurona</option></select>
<button onclick='save()'>Guardar</button><button class='secondary' onclick='health()'>Health 8010</button><button class='secondary' onclick='router()'>Consultar Router</button><button class='secondary' onclick='compat()'>Compatibilidad</button><button class='secondary' onclick='installQueue()'>Cola modelos</button><button class='secondary' onclick='semanticDoctor()'>Memoria semántica</button><button class='secondary' onclick='apply()'>Aplicar recomendados</button><button class='secondary' onclick='clearChat()'>Limpiar</button><div id='box' class='box'>Sin consultar.</div>
</aside><main class='card main'><div class='top'><b>Chat local auditable</b><br><span id='status'>Listo</span></div><section id='chat' class='chat'></section><div class='composer'><textarea id='msg' placeholder='Escribe... Ctrl+Enter' onkeydown='keysend(event)'></textarea><button onclick='send()'>Enviar</button></div></main></div>
<script>
const $=id=>document.getElementById(id);let lastRouter=null;const settings=['key','hyp','cen','intent','urgency','project','neuron','session','scope'];function save(){settings.forEach(k=>localStorage.setItem('triade_sp_'+k,$(k).value));localStorage.setItem('triade_sp_ollama',$('ollama').checked);localStorage.setItem('triade_sp_auto',$('auto').checked);status('Guardado',true)}function load(){settings.forEach(k=>{const v=localStorage.getItem('triade_sp_'+k);if(v!==null)$(k).value=v});$('ollama').checked=localStorage.getItem('triade_sp_ollama')==='true';$('auto').checked=localStorage.getItem('triade_sp_auto')!=='false'}function status(t,ok=false){$('status').textContent=t;$('status').className=ok?'ok':''}function add(cls,text,meta=''){let d=document.createElement('div');d.className='msg '+cls;d.textContent=text;if(meta){let m=document.createElement('div');m.className='meta';m.textContent=meta;d.appendChild(m)}$('chat').appendChild(d);$('chat').scrollTop=$('chat').scrollHeight}function eventLabel(e){let s=e.severity||'info';let a=e.action_required||'none';return 'Evento del sistema · '+s+' · acción: '+a}function addEvents(events){if(!Array.isArray(events)||!events.length)return;events.forEach(e=>{let cls='event '+(e.severity||'info');let msg='⚠ '+(e.message||e.type||'Evento del sistema');if(e.status)msg+='\nEstado: '+e.status;if(e.type)msg+='\nTipo: '+e.type;add(cls,msg,eventLabel(e))})}function context(){let c={};if($('project').value.trim())c.project_id=$('project').value.trim();if($('neuron').value.trim())c.active_neuron=$('neuron').value.trim();if($('session').value.trim())c.session_id=$('session').value.trim();if($('scope').value)c.context_scope=$('scope').value;return c}
async function health(){try{let r=await fetch('/api/health');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({mode:j.mode,hardware:j.hardware,contexts:j.doctor?.crystal_contexts,ollama:j.ollama?.ok,runs:j.doctor?.counts?.runs},null,2);status('Health OK',true)}catch(e){status('Health falló: '+e.message)}}
async function router(){try{let r=await fetch('/api/router/doctor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({intent:$('intent').value,urgency:$('urgency').value})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);lastRouter=j;let d=j.router.decisions;$('box').textContent=JSON.stringify({central:d.central?.selected_model,hypothalamus:d.hypothalamus?.selected_model,fast:d.fast?.selected_model,deep:d.deep?.selected_model},null,2);status('Router OK',true)}catch(e){status('Router falló: '+e.message)}}
async function compat(){try{let r=await fetch('/api/models/compatibility');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.matrix.summary,counts:j.matrix.counts,models:j.matrix.models},null,2);status('Compatibilidad OK',true)}catch(e){status('Compatibilidad falló: '+e.message)}}
async function installQueue(){try{let r=await fetch('/api/models/install-queue?include_allowed=false');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify({summary:j.summary,count:j.count,policy:j.policy,candidates:j.candidates},null,2);status('Cola OK',true)}catch(e){status('Cola falló: '+e.message)}}
async function semanticDoctor(){try{let r=await fetch('/api/semantic/governance/doctor');let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);$('box').textContent=JSON.stringify(j,null,2);status('Gobierno semántico consultado',true)}catch(e){status('Memoria semántica falló: '+e.message)}}
function apply(){if(!lastRouter){status('Consulta router primero');return}let d=lastRouter.router.decisions;if(d.hypothalamus?.selected_model)$('hyp').value=d.hypothalamus.selected_model;if(d.central?.selected_model)$('cen').value=d.central.selected_model;$('ollama').checked=true;$('auto').checked=false;save();status('Recomendados aplicados manualmente',true)}
async function send(){save();let text=$('msg').value.trim();if(!text)return;$('msg').value='';add('user',text);status('Procesando...');try{let r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json','X-TRIADE-API-Key':$('key').value},body:JSON.stringify({text,source:'single-port-ui',use_ollama:$('ollama').checked,hypothalamus_model:$('hyp').value,central_model:$('cen').value,auto_select_models:$('auto').checked,context:context()})});let j=await r.json();if(!r.ok)throw Error(j.detail||r.status);let t=j.crystal_temporal_state||{};add('bot',j.response,[j.run_id,'Q '+t.status,'scope '+t.context_scope,'ctx '+t.context_key,'H '+j.models?.hypothalamus?.name,'C '+j.models?.central?.name].filter(Boolean).join(' · '));addEvents(j.system_events);if(j.system_events?.length)$('box').textContent=JSON.stringify({system_events:j.system_events,run_id:j.run_id},null,2);status(j.system_events?.length?'Respuesta + eventos del sistema':'Respuesta recibida',true)}catch(e){add('bot','Error: '+e.message);status('Error')}}function clearChat(){$('chat').innerHTML=''}function keysend(e){if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))send()}load();add('bot','Tríade Ω lista. La memoria semántica autorizada requiere estado stable o autorización experimental explícita. Los eventos internos aparecerán como avisos separados cuando requieran revisión.');
</script></body></html>
"""


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def ui() -> str:
    return HTML
