#!/usr/bin/env bash
# Fuente única de verdad para levantar, parar y consultar Tríade Ω en local.
#
# No añade un arranque nuevo: envuelve el que ya era oficial —Single Port sobre
# `apps.single_port_app:app` en el 8010— para que host, puerto y modo no vivan
# repetidos en cada documento y acaben contradiciéndose.
#
#   scripts/triade_runtime.sh up      levanta Ollama (si falta) y la app
#   scripts/triade_runtime.sh down    para la app
#   scripts/triade_runtime.sh status  qué escucha el puerto y en qué modo
#   scripts/triade_runtime.sh restart down + up
#
# Por qué existe `down` aquí en vez de un `pkill` a mano: el patrón obvio
# (`pkill -f uvicorn`, `pgrep -f single_port_app`) coincide con la propia shell
# que lo ejecuta —y con cualquier comando que mencione el módulo—, así que se
# mata sola. Este script usa el PID del fichero, y sólo cae al listener real
# del puerto si no hay fichero.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="0.0.0.0"
PORT="${TRIADE_STUDIO_PORT:-8010}"
APP="apps.single_port_app:app"
URL="http://127.0.0.1:${PORT}"
PIDFILE="${ROOT}/logs/triade-runtime.pid"
LOG="${ROOT}/logs/studio-web.log"

cd "$ROOT"
mkdir -p logs

listener_pid() { ss -lntpH "sport = :${PORT}" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2; }

start_ollama() {
  if curl -sf --max-time 5 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "ollama: ya responde"
    return
  fi
  echo "ollama: arrancando"
  OLLAMA_MODELS="${OLLAMA_MODELS:-$HOME/.ollama/models}" \
    setsid nohup ollama serve > logs/ollama.log 2>&1 < /dev/null &
  for _ in $(seq 1 30); do
    sleep 2
    curl -sf --max-time 5 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && { echo "ollama: arriba"; return; }
  done
  echo "ollama: NO respondió a tiempo" >&2; exit 1
}

up() {
  if [ -n "$(listener_pid)" ]; then
    echo "ya hay algo escuchando en ${PORT}: $(listener_pid). Usa 'restart' o 'down'." >&2
    exit 1
  fi
  start_ollama
  # El .env trae modo, workers, rutas de Ollama y la clave de backup.
  set -a; . ./.env; set +a
  # El reinicio del Studio devuelve `0744` a todos los ficheros, y con la clave
  # abierta `EncryptedBackup` se niega a cifrar: el 2026-08-08 el organismo pasó
  # trece horas sin copia, con cada `encrypted_backup` en `dead_letter` y nada
  # que lo dijera hasta regenerar la deuda. El modo se cierra aquí, en la capa
  # que ya es dueña del entorno, y se dice en voz alta cuando hubo que tocarlo.
  echo -n "clave de backup: "
  python -c 'from triade.memory.encrypted_backup import EncryptedBackup as E; print(E.ensure_key_file_mode())'
  setsid nohup python -m uvicorn "$APP" --host "$HOST" --port "$PORT" \
    --proxy-headers --forwarded-allow-ips='*' > "$LOG" 2>&1 < /dev/null &
  echo $! > "$PIDFILE"
  echo "app: arrancando (log: ${LOG})"
  for _ in $(seq 1 40); do
    sleep 3
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${URL}/health/live")" = "200" ]; then
      echo "app: arriba en ${URL}"
      wait_for_workers
      status
      return
    fi
  done
  echo "app: NO respondió a tiempo; revisa ${LOG}" >&2; exit 1
}

# `/health/live` responde antes de que el organismo esté completo: el bucle de
# workers tarda otro minuto largo en darse por vivo. Dar el arranque por hecho
# ahí hacía fallar la certificación en falso —`workers_active: false` a los
# pocos segundos, `true` un minuto después— y esa carrera es del arranque, no
# de Tríade. `up` no vuelve hasta que el runtime es el que dice ser.
wait_for_workers() {
  echo -n "workers: esperando"
  for _ in $(seq 1 40); do
    if curl -s --max-time 20 "${URL}/api/runtime/heartbeat" 2>/dev/null \
      | python -c 'import sys,json;sys.exit(0 if json.load(sys.stdin).get("workers_active") else 1)' 2>/dev/null; then
      echo " activos"
      return 0
    fi
    echo -n "."
    sleep 5
  done
  echo " NO se activaron; el runtime está incompleto" >&2
  return 1
}

down() {
  local pid=""
  [ -f "$PIDFILE" ] && pid="$(cat "$PIDFILE")"
  # El PID del fichero es el del wrapper; quien tiene el puerto es el hijo.
  local lpid; lpid="$(listener_pid)"
  for p in $pid $lpid; do kill "$p" 2>/dev/null || true; done
  for _ in $(seq 1 10); do
    sleep 2
    [ -z "$(listener_pid)" ] && break
  done
  # El runtime completo no siempre cierra con SIGTERM: los hilos de fondo
  # (workers, metabolismo) pueden seguir vivos aunque el puerto ya esté libre.
  for p in $pid $lpid; do kill -9 "$p" 2>/dev/null || true; done
  rm -f "$PIDFILE"
  echo "app: parada"
}

status() {
  local lpid; lpid="$(listener_pid)"
  if [ -z "$lpid" ]; then echo "puerto ${PORT}: nada escuchando"; return; fi
  echo "puerto ${PORT}: pid ${lpid} ($(ps -o comm= -p "$lpid" 2>/dev/null))"
  echo "listeners en ${PORT}: $(ss -lntH "sport = :${PORT}" 2>/dev/null | wc -l) (debe ser 1)"
  echo "url: ${URL}"
  curl -s --max-time 120 "${URL}/health/deep" \
    | python -c 'import sys,json;d=json.load(sys.stdin);m=d.get("runtime_mode") or {};print("status:",d.get("status"),"| conversation_only:",m.get("conversation_only"),"| arranque:",m.get("status"))' \
    2>/dev/null || echo "health/deep: sin respuesta"
}

case "${1:-status}" in
  up) up ;;
  down) down ;;
  restart) down; up ;;
  status) status ;;
  *) echo "uso: $0 {up|down|restart|status}" >&2; exit 2 ;;
esac
