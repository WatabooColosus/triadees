#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${TRIADE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="${TRIADE_STATE_DIR:-$ROOT/.runtime/unidad01}"
LOG_DIR="${TRIADE_LOG_DIR:-$STATE_DIR/logs}"
PID_DIR="$STATE_DIR/pids"
REPORT="$STATE_DIR/activation-report.json"
HOST="${TRIADE_HOST:-127.0.0.1}"
API_PORT="${TRIADE_API_PORT:-8010}"
MODEL_PORT="${TRIADE_MODEL_PORT:-11434}"
UI_PORT="${TRIADE_UI_PORT:-8010}"
mkdir -p "$LOG_DIR" "$PID_DIR"

log(){ printf '[unidad-01] %s\n' "$*"; }
fail(){ log "ERROR: $*"; exit 1; }
command_exists(){ command -v "$1" >/dev/null 2>&1; }

service_exists(){
  systemctl list-unit-files "$1" --no-legend 2>/dev/null | grep -q "^$1"
}

start_service(){
  local unit="$1"
  if service_exists "$unit"; then
    log "Activando $unit"
    if [ "$(id -u)" -eq 0 ]; then
      systemctl enable --now "$unit"
    elif command_exists sudo; then
      sudo systemctl enable --now "$unit"
    else
      systemctl --user enable --now "$unit" || return 1
    fi
    return 0
  fi
  return 1
}

start_background(){
  local name="$1"; shift
  local pidfile="$PID_DIR/$name.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    log "$name ya está activo (PID $(cat "$pidfile"))"
    return 0
  fi
  log "Arrancando $name directamente"
  nohup "$@" >>"$LOG_DIR/$name.log" 2>&1 &
  echo $! >"$pidfile"
}

wait_http(){
  local name="$1" url="$2" attempts="${3:-30}"
  local i
  for ((i=1;i<=attempts;i++)); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      log "$name saludable: $url"
      return 0
    fi
    sleep 2
  done
  log "$name no respondió: $url"
  return 1
}

cd "$ROOT"
log "Raíz: $ROOT"

# 1. Proveedor de modelos
MODEL_STATUS="unavailable"
if start_service ollama.service || start_service triade-model-router.service; then
  MODEL_STATUS="service"
elif command_exists ollama; then
  start_background ollama ollama serve
  MODEL_STATUS="direct"
fi

# 2. Núcleo/API. Se prefieren las unidades existentes del repositorio.
API_STATUS="unavailable"
for unit in triade.service triade-api.service; do
  if start_service "$unit"; then API_STATUS="service:$unit"; break; fi
done

if [ "$API_STATUS" = "unavailable" ]; then
  PYTHON_BIN="${TRIADE_PYTHON:-}"
  if [ -z "$PYTHON_BIN" ]; then
    if [ -x "$ROOT/.venv/bin/python" ]; then PYTHON_BIN="$ROOT/.venv/bin/python";
    elif command_exists python3; then PYTHON_BIN="$(command -v python3)";
    else fail "Python no encontrado"; fi
  fi

  if [ -f "$ROOT/apps/main.py" ]; then
    start_background triade-api "$PYTHON_BIN" -m uvicorn apps.main:app --host "$HOST" --port "$API_PORT"
    API_STATUS="direct:apps.main:app"
  elif [ -f "$ROOT/main.py" ]; then
    start_background triade-api "$PYTHON_BIN" -m uvicorn main:app --host "$HOST" --port "$API_PORT"
    API_STATUS="direct:main:app"
  else
    fail "No se encontró una entrada API compatible"
  fi
fi

# 3. UI, si está desacoplada. Si comparte puerto/API, la comprobación HTTP basta.
UI_STATUS="integrated"
if start_service triade-chat-ui.service; then
  UI_STATUS="service:triade-chat-ui.service"
elif [ -x "$ROOT/scripts/start_studio_web.sh" ]; then
  # Solo se usa si la API aún no ofrece UI; evita duplicar procesos.
  if ! curl -fsS --max-time 2 "http://$HOST:$UI_PORT/" >/dev/null 2>&1; then
    start_background triade-ui "$ROOT/scripts/start_studio_web.sh"
    UI_STATUS="direct:start_studio_web.sh"
  fi
fi

# 4. Salud: probar varias rutas conocidas sin asumir una sola implementación.
API_URL=""
for path in /health /api/health /healthz /; do
  if wait_http "Tríade API" "http://$HOST:$API_PORT$path" 15; then
    API_URL="http://$HOST:$API_PORT$path"
    break
  fi
done
[ -n "$API_URL" ] || fail "La API no alcanzó estado saludable"

MODEL_HEALTH="not-required"
if curl -fsS --max-time 3 "http://$HOST:$MODEL_PORT/api/tags" >/dev/null 2>&1; then
  MODEL_HEALTH="healthy"
elif [ "$MODEL_STATUS" != "unavailable" ]; then
  MODEL_HEALTH="degraded"
fi

NOW="$(date -Iseconds)"
HOSTNAME_VALUE="$(hostname)"
cat >"$REPORT" <<JSON
{
  "unit": "Unidad 01",
  "timestamp": "$NOW",
  "hostname": "$HOSTNAME_VALUE",
  "root": "$ROOT",
  "api": {"status": "$API_STATUS", "health": "healthy", "url": "$API_URL"},
  "ui": {"status": "$UI_STATUS", "url": "http://$HOST:$UI_PORT/"},
  "model_runtime": {"status": "$MODEL_STATUS", "health": "$MODEL_HEALTH", "url": "http://$HOST:$MODEL_PORT/"},
  "activation": "successful"
}
JSON

log "ACTIVACIÓN EXITOSA"
cat "$REPORT"
