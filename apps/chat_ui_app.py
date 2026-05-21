"""Interfaz web local de chat para Tríade Ω.

Servidor ligero independiente que entrega una UI HTML/JS y se comunica con
la API principal en http://127.0.0.1:8000/triade/run.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Tríade Ω Chat UI", version="0.1.0")


HTML = r"""
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Tríade Ω · Chat Local</title>
  <style>
    :root {
      --bg: #090b10;
      --panel: #121722;
      --panel-2: #171f2e;
      --text: #edf2ff;
      --muted: #9aa7bd;
      --accent: #8fd3ff;
      --ok: #9bffb1;
      --warn: #ffd88f;
      --border: #263246;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(circle at top left, #172033 0, #090b10 42%, #06070a 100%);
      color: var(--text);
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      min-height: 100vh;
      display: flex;
      justify-content: center;
      padding: 22px;
    }
    .app {
      width: min(1080px, 100%);
      display: grid;
      grid-template-columns: 300px 1fr;
      gap: 18px;
    }
    .card {
      background: rgba(18, 23, 34, 0.92);
      border: 1px solid var(--border);
      border-radius: 22px;
      box-shadow: 0 20px 70px rgba(0,0,0,.35);
    }
    .side { padding: 18px; height: calc(100vh - 44px); position: sticky; top: 22px; }
    .brand { font-size: 24px; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 6px; }
    .subtitle { color: var(--muted); font-size: 13px; line-height: 1.4; margin-bottom: 18px; }
    label { display: block; color: var(--muted); font-size: 12px; margin: 14px 0 6px; }
    input, textarea, select {
      width: 100%;
      background: var(--panel-2);
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 12px;
      padding: 11px 12px;
      outline: none;
    }
    input:focus, textarea:focus { border-color: var(--accent); }
    .row { display: flex; gap: 8px; align-items: center; }
    .row input[type="checkbox"] { width: auto; }
    button {
      border: 0;
      background: linear-gradient(135deg, #73c7ff, #9bffb1);
      color: #061018;
      font-weight: 800;
      border-radius: 14px;
      padding: 12px 14px;
      cursor: pointer;
      width: 100%;
      margin-top: 14px;
    }
    button.secondary { background: #223047; color: var(--text); border: 1px solid var(--border); }
    .main { display: flex; flex-direction: column; height: calc(100vh - 44px); overflow: hidden; }
    .topbar { padding: 16px 18px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; gap: 12px; align-items: center; }
    .status { color: var(--muted); font-size: 13px; }
    .status.ok { color: var(--ok); }
    .chat { flex: 1; overflow: auto; padding: 18px; display: flex; flex-direction: column; gap: 14px; }
    .msg { max-width: 86%; padding: 14px 15px; border-radius: 18px; line-height: 1.48; white-space: pre-wrap; }
    .user { align-self: flex-end; background: #1f6feb; }
    .bot { align-self: flex-start; background: var(--panel-2); border: 1px solid var(--border); }
    .meta { color: var(--muted); font-size: 12px; margin-top: 9px; border-top: 1px solid rgba(255,255,255,.08); padding-top: 8px; }
    .composer { padding: 16px; border-top: 1px solid var(--border); display: grid; grid-template-columns: 1fr 130px; gap: 10px; }
    .composer textarea { resize: none; min-height: 52px; max-height: 140px; }
    .composer button { margin-top: 0; height: 52px; }
    .small { font-size: 12px; color: var(--muted); line-height: 1.45; margin-top: 10px; }
    @media (max-width: 820px) {
      body { padding: 10px; }
      .app { grid-template-columns: 1fr; }
      .side { position: static; height: auto; }
      .main { height: 72vh; }
      .composer { grid-template-columns: 1fr; }
      .composer button { height: auto; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="card side">
      <div class="brand">Tríade Ω</div>
      <div class="subtitle">Chat local para probar respuestas, memoria, modelos y runs auditables.</div>

      <label>API base</label>
      <input id="apiBase" value="http://127.0.0.1:8000" />

      <label>API key local</label>
      <input id="apiKey" type="password" placeholder="X-TRIADE-API-Key" />

      <label>Modelo Hipotálamo</label>
      <input id="hypModel" value="qwen2.5:3b-instruct" />

      <label>Modelo Central</label>
      <input id="cenModel" value="qwen2.5:3b-instruct" />

      <label class="row"><input id="useOllama" type="checkbox" /> Usar Ollama</label>

      <button onclick="saveSettings()">Guardar ajustes</button>
      <button class="secondary" onclick="checkHealth()">Probar health</button>
      <button class="secondary" onclick="clearChat()">Limpiar chat</button>

      <div class="small">
        Consejo: empieza sin Ollama para respuestas rápidas. Luego activa Ollama para evaluar calidad real del modelo local.
      </div>
    </aside>

    <main class="card main">
      <div class="topbar">
        <div>
          <strong>Chat local auditable</strong><br />
          <span class="status" id="status">Listo.</span>
        </div>
        <span class="status" id="lastRun">sin run</span>
      </div>
      <section class="chat" id="chat"></section>
      <div class="composer">
        <textarea id="message" placeholder="Escribe a Tríade..." onkeydown="handleKey(event)"></textarea>
        <button onclick="sendMessage()">Enviar</button>
      </div>
    </main>
  </div>

  <script>
    const els = {
      apiBase: document.getElementById('apiBase'),
      apiKey: document.getElementById('apiKey'),
      hypModel: document.getElementById('hypModel'),
      cenModel: document.getElementById('cenModel'),
      useOllama: document.getElementById('useOllama'),
      status: document.getElementById('status'),
      lastRun: document.getElementById('lastRun'),
      chat: document.getElementById('chat'),
      message: document.getElementById('message'),
    };

    function loadSettings() {
      els.apiBase.value = localStorage.getItem('triade_api_base') || els.apiBase.value;
      els.apiKey.value = localStorage.getItem('triade_api_key') || '';
      els.hypModel.value = localStorage.getItem('triade_hyp_model') || els.hypModel.value;
      els.cenModel.value = localStorage.getItem('triade_cen_model') || els.cenModel.value;
      els.useOllama.checked = localStorage.getItem('triade_use_ollama') === 'true';
    }

    function saveSettings() {
      localStorage.setItem('triade_api_base', els.apiBase.value.trim());
      localStorage.setItem('triade_api_key', els.apiKey.value.trim());
      localStorage.setItem('triade_hyp_model', els.hypModel.value.trim());
      localStorage.setItem('triade_cen_model', els.cenModel.value.trim());
      localStorage.setItem('triade_use_ollama', String(els.useOllama.checked));
      setStatus('Ajustes guardados.', true);
    }

    function setStatus(text, ok=false) {
      els.status.textContent = text;
      els.status.className = ok ? 'status ok' : 'status';
    }

    function addMessage(role, text, meta='') {
      const div = document.createElement('div');
      div.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
      div.textContent = text;
      if (meta) {
        const m = document.createElement('div');
        m.className = 'meta';
        m.textContent = meta;
        div.appendChild(m);
      }
      els.chat.appendChild(div);
      els.chat.scrollTop = els.chat.scrollHeight;
    }

    async function checkHealth() {
      saveSettings();
      try {
        const res = await fetch(els.apiBase.value.trim() + '/health');
        const data = await res.json();
        setStatus('Health: ' + data.status + ' · runs=' + (data.doctor?.counts?.runs ?? '?'), res.ok);
      } catch (err) {
        setStatus('Health falló: ' + err.message);
      }
    }

    async function sendMessage() {
      saveSettings();
      const text = els.message.value.trim();
      if (!text) return;
      els.message.value = '';
      addMessage('user', text);
      setStatus('Procesando...');

      const payload = {
        text,
        source: 'chat-ui-local',
        use_ollama: els.useOllama.checked,
        hypothalamus_model: els.hypModel.value.trim() || null,
        central_model: els.cenModel.value.trim() || null,
      };

      try {
        const res = await fetch(els.apiBase.value.trim() + '/triade/run', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-TRIADE-API-Key': els.apiKey.value.trim(),
          },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Error HTTP ' + res.status);
        els.lastRun.textContent = data.run_id || 'run generado';
        const hyp = data.models?.hypothalamus;
        const cen = data.models?.central;
        const meta = [
          data.run_id ? 'run: ' + data.run_id : '',
          data.run_path ? 'path: ' + data.run_path : '',
          hyp ? 'H: ' + hyp.name + ' ok=' + hyp.ok : '',
          cen ? 'C: ' + cen.name + ' ok=' + cen.ok : '',
        ].filter(Boolean).join(' · ');
        addMessage('bot', data.response || '(sin respuesta)', meta);
        setStatus('Respuesta recibida.', true);
      } catch (err) {
        addMessage('bot', 'Error: ' + err.message);
        setStatus('Error al enviar.');
      }
    }

    function handleKey(event) {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        sendMessage();
      }
    }

    function clearChat() {
      els.chat.innerHTML = '';
      els.lastRun.textContent = 'sin run';
      setStatus('Chat limpiado.', true);
    }

    loadSettings();
    addMessage('bot', 'Tríade Ω lista. Escribe un mensaje y presiona Enviar. Usa Ctrl+Enter para enviar rápido.');
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
