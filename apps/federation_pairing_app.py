"""Portal local de emparejamiento federado consentido."""

from __future__ import annotations

import os
import re
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from triade.federation.federation import Federation
from triade.core.repo_info import repo_info


DB_PATH = os.environ.get("TRIADE_DB_PATH", "triade/memory/triade.db")
PAIRING_TOKEN = os.environ.get("TRIADE_PAIRING_TOKEN", "")

app = FastAPI(title="Triade Federation Pairing", version="0.1")


class PairRequest(BaseModel):
    token: str = Field(..., min_length=1)
    display_name: str = Field(default="Dispositivo movil", min_length=1, max_length=80)
    permissions: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "mode": "federation-pairing", "pairing_enabled": True, "repo": repo_info()}


@app.get("/api/repo")
def repo() -> dict[str, Any]:
    return repo_info()


@app.get("/", response_class=HTMLResponse)
def pairing_page(token: str = "") -> str:
    return HTML.replace("__TOKEN__", _escape(token))


@app.get("/admin", response_class=HTMLResponse)
def admin_help(request: Request) -> str:
    central_url = str(request.base_url).rstrip("/")
    install_cmd = f"curl -fsSL {central_url}/downloads/termux-bootstrap.sh | bash"
    return (
        ADMIN_HELP_HTML
        .replace("__INSTALL_CMD__", _escape(install_cmd))
    )


@app.get("/downloads/termux-bootstrap.sh", response_class=PlainTextResponse)
def termux_bootstrap(request: Request) -> PlainTextResponse:
    central_url = str(request.base_url).rstrip("/")
    script = TERMUX_BOOTSTRAP.replace("__CENTRAL_URL__", central_url).replace("__PAIRING_TOKEN__", "")
    return PlainTextResponse(
        script,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="triade-termux-bootstrap.sh"'},
    )


@app.post("/api/pair")
def pair_device(request: PairRequest) -> dict[str, Any]:
    if not PAIRING_TOKEN:
        raise HTTPException(status_code=503, detail="TRIADE_PAIRING_TOKEN no configurado.")
    if request.token != PAIRING_TOKEN:
        raise HTTPException(status_code=401, detail="Token de emparejamiento invalido.")

    allowed_permissions = {
        "publish_capabilities",
        "request_compute",
        "request_sandbox_test",
    }
    permissions = sorted(set(request.permissions) & allowed_permissions)
    if "publish_capabilities" not in permissions:
        permissions.insert(0, "publish_capabilities")

    node_id = _node_id(request.display_name)
    capabilities = _normalize_browser_capabilities(request.capabilities)
    federation = Federation(db_path=DB_PATH)
    node = federation.register_node(
        node_id=node_id,
        name=request.display_name.strip(),
        owner="pairing-portal",
        trust_level="low",
        permissions=permissions,
        capabilities=capabilities,
    )
    return {
        "status": "ok",
        "node": node,
        "note": "Nodo navegador registrado. Mantener esta pagina abierta para futuras capacidades interactivas.",
    }


def _node_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "browser-node"
    return f"{slug}-{uuid4().hex[:8]}"


def _normalize_browser_capabilities(payload: dict[str, Any]) -> dict[str, Any]:
    cpu_count = int(payload.get("hardware_concurrency") or 1)
    ram = float(payload.get("device_memory_gb") or 0.0)
    screen = payload.get("screen") if isinstance(payload.get("screen"), dict) else {}
    return {
        "tier": "low",
        "cpu_count": cpu_count,
        "ram_total_gb": ram,
        "ram_available_gb": 0.0,
        "gpus": [],
        "browser_node": True,
        "background_execution": False,
        "user_agent": str(payload.get("user_agent") or "unknown")[:300],
        "platform": str(payload.get("platform") or "unknown")[:120],
        "screen": screen,
        "notes": [
            "Nodo emparejado desde navegador movil.",
            "Capacidades limitadas por sandbox del navegador.",
            "Para GPU/CPU sostenida se requiere agente nativo o Termux.",
        ],
    }


def _escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


HTML = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Tríade Ω · Emparejar nodo</title>
  <style>
    :root{color-scheme:dark light;font-family:system-ui,-apple-system,Segoe UI,sans-serif}
    body{margin:0;background:#101216;color:#f3f5f7}
    main{max-width:680px;margin:0 auto;padding:28px 18px 42px}
    h1{font-size:28px;margin:0 0 8px}
    p{line-height:1.45;color:#c9d0d8}
    label{display:block;margin:16px 0 6px;color:#eef2f6}
    input[type=text]{box-sizing:border-box;width:100%;padding:13px 12px;border-radius:8px;border:1px solid #39414d;background:#171b22;color:#fff;font-size:16px}
    .perm{display:flex;gap:10px;align-items:flex-start;padding:12px 0;border-bottom:1px solid #2a3039}
    .perm input{margin-top:3px}
    button{margin-top:18px;width:100%;padding:14px 16px;border:0;border-radius:8px;background:#4fb477;color:#07130c;font-weight:700;font-size:16px}
    pre{white-space:pre-wrap;background:#171b22;border:1px solid #2f3742;border-radius:8px;padding:12px;overflow:auto}
    .muted{font-size:13px;color:#9fa8b3}
    .ok{color:#7de29c}.bad{color:#ff8d8d}
  </style>
</head>
<body>
<main>
  <h1>Tríade Ω · Emparejar este dispositivo</h1>
  <p>Autoriza este equipo como nodo federado local. El navegador solo publica capacidades y permisos; no lee archivos, no toma control del sistema y no ejecuta comandos arbitrarios.</p>
  <pre id="repo">Cargando repositorio...</pre>

  <label>Nombre del dispositivo</label>
  <input id="name" type="text" value="Celular de Santiago"/>

  <label>Token de emparejamiento</label>
  <input id="token" type="text" value="__TOKEN__" placeholder="Pega el token autorizado"/>

  <div class="perm"><input id="pub" type="checkbox" checked disabled/><div><b>Publicar capacidades</b><div class="muted">CPU aproximada, memoria expuesta por navegador, pantalla y plataforma.</div></div></div>
  <div class="perm"><input id="compute" type="checkbox" checked/><div><b>Permitir trabajos controlados</b><div class="muted">Reservado para jobs encapsulados futuros mientras esta página esté abierta.</div></div></div>
  <div class="perm"><input id="sandbox" type="checkbox" checked/><div><b>Permitir pruebas sandbox</b><div class="muted">Benchmarks ligeros y verificación de disponibilidad.</div></div></div>

  <button onclick="pair()">Autorizar nodo</button>
  <p id="status" class="muted">Esperando autorización.</p>
  <pre id="out"></pre>
</main>
<script>
const token = "__TOKEN__";
async function loadRepo(){
  try{
    const r = await fetch("/api/repo");
    const j = await r.json();
    document.getElementById("repo").textContent = JSON.stringify({
      origin:j.origin, branch:j.branch, commit:j.commit, upstream:j.upstream, dirty:j.dirty, changed_files:j.changed_files
    }, null, 2);
  }catch(e){
    document.getElementById("repo").textContent = "Repositorio no disponible: " + e.message;
  }
}
function capabilities(){
  return {
    hardware_concurrency: navigator.hardwareConcurrency || 1,
    device_memory_gb: navigator.deviceMemory || 0,
    user_agent: navigator.userAgent,
    platform: navigator.platform,
    screen: {width: screen.width, height: screen.height, pixel_ratio: window.devicePixelRatio || 1}
  };
}
async function pair(){
  const permissions = ["publish_capabilities"];
  if(document.getElementById("compute").checked) permissions.push("request_compute");
  if(document.getElementById("sandbox").checked) permissions.push("request_sandbox_test");
  document.getElementById("status").textContent = "Registrando nodo...";
  try{
    const r = await fetch("/api/pair", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({
      token: document.getElementById("token").value.trim(),
      display_name: document.getElementById("name").value.trim() || "Dispositivo movil",
      permissions, capabilities: capabilities()
    })});
    const j = await r.json();
    if(!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail || j));
    document.getElementById("status").textContent = "Nodo autorizado.";
    document.getElementById("status").className = "ok";
    document.getElementById("out").textContent = JSON.stringify(j, null, 2);
  }catch(e){
    document.getElementById("status").textContent = "Error: " + (e.message || String(e));
    document.getElementById("status").className = "bad";
  }
}
loadRepo();
</script>
</body>
</html>
"""


ADMIN_HELP_HTML = """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Tríade Ω · Preparar agente Termux</title>
  <style>
    body{font-family:system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#101216;color:#f4f6f8}
    main{max-width:920px;margin:0 auto;padding:28px 18px}
    code,pre{background:#171b22;border:1px solid #303946;border-radius:8px}
    code{padding:2px 5px}pre{padding:12px;white-space:pre-wrap;overflow:auto}
    p{line-height:1.45;color:#cbd3dc}
    h2{margin-top:26px}
    button{border:0;border-radius:8px;background:#61c184;color:#07130c;font-weight:800;padding:10px 12px;margin:6px 0 12px}
    .note{border-left:4px solid #61c184;padding:10px 12px;background:#171b22;color:#dbe5ef}
  </style>
</head>
<body>
<main>
  <h1>Preparar celular como nodo Tríade</h1>
  <p>Esta página pertenece a la PC central. El panel real del celular aparece cuando el agente corre dentro de Termux en el celular.</p>
  <div class="note">Objetivo: instalar dependencias, copiar o clonar el repo, iniciar el agente al 60% y abrir <code>http://localhost:8790/admin</code> desde el celular.</div>

  <h2>1. Instalar Termux y dependencias</h2>
  <p>Opción recomendada: desde Termux ejecuta un solo comando. El instalador hace el resto.</p>
  <button onclick="copy('onecmd')">Copiar instalador automático</button>
  <pre id="onecmd">__INSTALL_CMD__</pre>

  <p>Si prefieres descargar el archivo desde el navegador:</p>
  <pre><a href="/downloads/termux-bootstrap.sh">Descargar triade-termux-bootstrap.sh</a></pre>

  <h2>Instalación manual alternativa</h2>
  <button onclick="copy('deps')">Copiar comandos</button>
  <pre id="deps">pkg update
pkg install python git
python -m pip install fastapi uvicorn pydantic</pre>

  <h2>2. Obtener el repositorio</h2>
  <p>Si el repo está en GitHub y el celular tiene acceso:</p>
  <button onclick="copy('clone')">Copiar clone</button>
  <pre id="clone">git clone https://github.com/WatabooColosus/triadees.git triadees
cd triadees</pre>

  <p>Si lo copiaste manualmente a Descargas:</p>
  <button onclick="copy('manual')">Copiar ruta manual</button>
  <pre id="manual">termux-setup-storage
cd /sdcard/Download/triadees
ls apps/mobile_node_agent.py</pre>

  <h2>3. Iniciar agente móvil</h2>
  <p>Usa este token local para el agente del celular. Puedes cambiarlo si quieres.</p>
  <button onclick="copy('run')">Copiar arranque</button>
  <pre id="run">export TRIADE_NODE_TOKEN="triade-mobile-8790"
python apps/mobile_node_agent.py \
  --host 0.0.0.0 \
  --port 8790 \
  --node-id celular-santiago \
  --usage 60 \
  --admin-root /sdcard/Download</pre>

  <h2>4. Abrir admin en el celular</h2>
  <button onclick="copy('local')">Copiar link local</button>
  <pre id="local">http://localhost:8790/admin</pre>
  <p>En ese panel escribe el token:</p>
  <pre>triade-mobile-8790</pre>

  <h2>5. Probar desde la PC central</h2>
  <p>Primero mira la IP del celular en WiFi. En Termux puedes usar:</p>
  <pre>ip addr show wlan0</pre>
  <p>Luego desde PowerShell en la PC, reemplaza <code>IP_DEL_CELULAR</code>:</p>
  <button onclick="copy('pc')">Copiar prueba PC</button>
  <pre id="pc">$TOKEN="triade-mobile-8790"
Invoke-RestMethod http://IP_DEL_CELULAR:8790/health
Invoke-RestMethod http://IP_DEL_CELULAR:8790/capabilities -Headers @{Authorization="Bearer $TOKEN"}</pre>

  <h2>6. Registrar como nodo operativo</h2>
  <button onclick="copy('register')">Copiar registro</button>
  <pre id="register">$TOKEN="triade-mobile-8790"
$CAPS = Invoke-RestMethod http://IP_DEL_CELULAR:8790/capabilities -Headers @{Authorization="Bearer $TOKEN"}
python triade_digimon.py federate register celular-termux `
  --name "Celular Termux" `
  --endpoint http://IP_DEL_CELULAR:8790 `
  --trust medium `
  --permission publish_capabilities `
  --permission request_compute `
  --capabilities ($CAPS | ConvertTo-Json -Depth 8)</pre>

  <h2>Portal de emparejamiento navegador</h2>
  <p>El token de emparejamiento no se publica en esta pagina. Definelo como variable local y compartelo solo por un canal confiable.</p>
  <pre>set TRIADE_PAIRING_TOKEN=token-local-seguro</pre>
  <p>Ese portal solo registra el navegador; el acceso real a recursos requiere el agente nativo o Termux anterior.</p>
</main>
<script>
async function copy(id){
  const text=document.getElementById(id).textContent;
  try{await navigator.clipboard.writeText(text)}catch(e){}
}
</script>
</body>
</html>
"""


TERMUX_BOOTSTRAP = r"""#!/data/data/com.termux/files/usr/bin/bash
set -e

REPO_URL="${TRIADE_REPO_URL:-https://github.com/WatabooColosus/triadees.git}"
APP_DIR="${TRIADE_APP_DIR:-$HOME/triadees}"
NODE_ID="${TRIADE_NODE_ID:-celular-santiago}"
NODE_TOKEN="${TRIADE_NODE_TOKEN:-triade-mobile-8790}"
USAGE="${TRIADE_USAGE:-60}"
PORT="${TRIADE_PORT:-8790}"
ADMIN_ROOT="${TRIADE_ADMIN_ROOT:-$HOME}"
CENTRAL_URL="${TRIADE_CENTRAL_URL:-__CENTRAL_URL__}"
PAIRING_TOKEN="${TRIADE_PAIRING_TOKEN:-__PAIRING_TOKEN__}"

echo "[Tríade] Preparando Termux..."
pkg update -y
pkg install -y python git curl
python -m pip install fastapi uvicorn pydantic

if [ -d "$APP_DIR/.git" ]; then
  echo "[Tríade] Actualizando repo en $APP_DIR"
  cd "$APP_DIR"
  git fetch origin
  git pull --ff-only || true
else
  echo "[Tríade] Clonando repo en $APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
  cd "$APP_DIR"
fi

cat > "$HOME/start-triade-mobile.sh" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
cd "$APP_DIR"
export TRIADE_NODE_TOKEN="$NODE_TOKEN"
export TRIADE_NODE_ID="$NODE_ID"
python apps/mobile_node_agent.py \\
  --host 0.0.0.0 \\
  --port "$PORT" \\
  --node-id "$NODE_ID" \\
  --usage "$USAGE" \\
  --admin-root "$ADMIN_ROOT"
EOF
chmod +x "$HOME/start-triade-mobile.sh"

IP="$(ip -4 addr show wlan0 2>/dev/null | awk '/inet / {print $2}' | cut -d/ -f1 | head -n1)"
if [ -z "$IP" ]; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi

cat <<EOF

[Tríade] Instalación lista.

Para iniciar el nodo móvil:
  ~/start-triade-mobile.sh

Luego abre en este celular:
  http://localhost:$PORT/admin

Token del agente:
  $NODE_TOKEN

Si la PC central necesita registrar este nodo, usa IP aproximada:
  http://$IP:$PORT

Portal central usado para descargar:
  $CENTRAL_URL

EOF

echo "[Tríade] Iniciando agente ahora..."
exec "$HOME/start-triade-mobile.sh"
"""
