"""Tríade Ω — Constantes HTML para la interfaz 8010.
Extraídas de single_port_app.py para mantener separación
de capas entre servicios, rutas y presentación.
"""
from __future__ import annotations
CLEAN_UI_HTML = """\
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
    <section class="section"><h2>Recursos locales</h2><div id="resources"></div></section>
    <section class="section"><h2>Federación Android</h2><div id="federation"></div></section>
    <section class="section"><h2>Modelos</h2><div id="models"></div></section>
    <section class="section"><h2>Gobierno de memoria</h2><div id="memory"></div></section>
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
  $('actions').innerHTML=`<div class="section">
    <h2>Acciones reales</h2>
    <button onclick="refresh()">Actualizar estado</button>
    <div class="small">Solo consulta datos vivos. No modifica memoria, neuronas ni repositorio.</div>
  </div>`;
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


function fmt(v){
  if(v===undefined||v===null||v==='') return '?';
  if(typeof v==='number') return Math.round(v*100)/100;
  return v;
}

function renderResources(){
  const c=state.capacity||{}, local=c.local||{}, h=local.hardware||{}, ollama=local.ollama||{}, docker=local.docker||{};
  const counts=local.counts||{};
  $('resources').innerHTML=`<div class="grid">
    <div class="card metric"><b>${esc(h.tier||'?')}</b><span>Tier local</span></div>
    <div class="card metric"><b>${esc(fmt(h.ram_available_gb))}</b><span>GB RAM libre</span></div>
    <div class="card metric"><b class="${ollama.ok?'ok':'warn'}">${ollama.ok?'activo':'pendiente'}</b><span>Ollama</span></div>
    <div class="card metric"><b class="${docker.ok?'ok':'warn'}">${docker.ok?'activo':'pendiente'}</b><span>Docker</span></div>
  </div>
  <div class="card small">Modelos · recomendados: ${counts.recommended||0} · permitidos: ${counts.allowed||0} · bloqueados: ${counts.blocked||0}</div>`;
}

function renderFederation(){
  const f=(state.capacity||{}).federation||{}, a=f.authorized||{}, nodes=f.online_feeders||[], hosts=f.llm_hosts||[];
  $('federation').innerHTML=`<div class="grid">
    <div class="card metric"><b>${nodes.length}</b><span>Nodos online</span></div>
    <div class="card metric"><b>${hosts.length}</b><span>Hosts LLM Android</span></div>
    <div class="card metric"><b>${fmt(a.cpu_authorized_count||0)}</b><span>CPU autorizada</span></div>
    <div class="card metric"><b>${fmt(a.ram_authorized_gb||0)}</b><span>GB RAM autorizada</span></div>
  </div>` + nodes.slice(0,4).map(n=>`<div class="card small"><b>${esc(n.name||n.node_id)}</b><br>RAM ${fmt(n.ram_authorized_gb)}/${fmt(n.ram_available_gb)} GB · score ${fmt(n.benchmark_score||0)} · ${n.can_host_llm?'host LLM':'feed/runtime'}</div>`).join('');
}

function renderModels(){
  const local=(state.capacity||{}).local||{}, auth=((state.capacity||{}).federation||{}).authorized||{};
  const recommended=local.recommended_models||[], allowed=local.allowed_models||[], aggregate=auth.runnable_by_aggregate_ram||[];
  const pills=[...aggregate.map(m=>`<span class="pill ok">${esc(m.model)} por suma</span>`),...recommended.map(m=>`<span class="pill ok">${esc(m.model)}</span>`),...allowed.slice(0,8).map(m=>`<span class="pill">${esc(m.model)}</span>`)].join('');
  const missing=(local.missing_for_comfortable_models||[]).slice(0,5).map(x=>`<div class="small">• ${esc(x)}</div>`).join('');
  $('models').innerHTML=`<div class="card">${pills||'<span class="muted">Sin modelos listados.</span>'}</div><div class="card">${missing||'<span class="muted">Sin faltantes críticos listados.</span>'}</div>`;
}

async function renderMemory(){
  try{
    const j=await api('/api/semantic/governance/doctor');
    const status=j.status||j.mode||'consultado';
    const policy=j.policy||'stable_or_explicit_experimental_required';
    $('memory').innerHTML=`<div class="card">
      <b>Memoria semántica</b><br>
      <span class="small">Estado: ${esc(status)}</span><br>
      <span class="small">Política: ${esc(policy)}</span><br>
      <span class="pill warn">sin stable = protección activa</span>
    </div>`;
  }catch(e){
    $('memory').innerHTML=`<div class="card"><b>Memoria semántica</b><br><span class="small">Protegida o no disponible: ${esc(e.message)}</span></div>`;
  }
}


function renderNeurons(){
  const n=state.neurons||{};
  const list=n.neurons||[];
  $('neurons').innerHTML=`<div class="grid">
    <div class="card metric"><b>${n.summary?.total_neurons??0}</b><span>Total</span></div>
    <div class="card metric"><b>${n.summary?.ready_for_stable_review??0}</b><span>Ready stable</span></div>
  </div>` + list.slice(0,8).map(x=>{
    const actions=(x.ui_actions||[]).map(a=>{
      const enabled=!!a.enabled;
      const reason=a.disabled_reason||'Acción requiere endpoint real o revisión humana.';
      return `<div class="card small">
        <b>${esc(a.label)}</b><br>
        <span class="${enabled?'ok':'warn'}">${enabled?'Disponible':'Bloqueada'}</span>
        ${enabled?'':`<br><span>${esc(reason)}</span>`}
      </div>`;
    }).join('');

    return `<div class="card">
      <b>${esc(x.name)}</b><br>
      <span class="small">${esc(x.status)} · ${esc(x.domain)}</span>
      <div class="small">act:${x.evidence?.activation_count||0} · diag:${x.evidence?.diagnosis_count||0} · tests:${x.evidence?.test_plan_count||0}</div>
      <div class="small">último run: ${esc(x.evidence?.last_run_id||'sin evidencia')}</div>
      ${actions}
    </div>`;
  }).join('') || '<div class="card small">No hay neuronas registradas.</div>';
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


function summarizeRunMeta(j){
  const events=j.system_events||[];
  const candidates=events.filter(e=>e.type==='background_neuron_candidate');
  const grouped={};
  for(const e of candidates){
    const p=e.payload||{};
    const domain=p.creator_spec?.domain||p.domain||'general';
    grouped[domain]=(grouped[domain]||0)+1;
  }
  const candidateText=candidates.length
    ? `candidatas ${candidates.length} (${Object.entries(grouped).map(([k,v])=>k+':'+v).join(', ')})`
    : 'sin candidatas';

  const safety=j.safety?.status ? `safety ${j.safety.status}` : '';
  const report=j.report?.status ? `report ${j.report.status}` : '';
  const h=j.models?.hypothalamus?.name ? `H ${j.models.hypothalamus.name}` : '';
  const c=j.models?.central?.name ? `C ${j.models.central.name}` : '';

  return [j.run_id,candidateText,safety,report,h,c].filter(Boolean).join(' · ');
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
    add('bot',j.response||'(sin respuesta)',summarizeRunMeta(j));
    setStatus('Respuesta recibida',true); await refresh();
  }catch(e){add('bot','Error: '+e.message);setStatus('Error')}
  state.busy=false; $('sendBtn').disabled=false;
}

async function refresh(){
  try{
    state.pulse=await api('/api/system/pulse?sync_relay=true');
    state.capacity=await api('/api/system/model-capacity?sync_relay=true');
    state.neurons=await api('/api/system/neurons?limit=50');
    renderLive(); renderResources(); renderFederation(); renderModels(); await renderMemory(); renderNeurons();
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
HTML = """\
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
  let html='<b>Neuronas candidatas</b><br><span class="hint">Candidate → auto-promoción → experimental. Ciclo autónomo 24/7.</span>';
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
  let html='<b>Neuronas candidatas</b><br><span class="hint">Candidate → auto-promoción → experimental. Ciclo autónomo 24/7.</span>';
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
TRIADE_UI_HTML = """\
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
TRIADE_REACT_UI_HTML = r"""\
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
