#!/usr/bin/env bash
# Fuente única de verdad para levantar, parar y consultar Tríade Ω en local.
#
#   scripts/triade_runtime.sh up      instala/habilita las units y arranca
#   scripts/triade_runtime.sh down    para la app (y no la deja volver sola)
#   scripts/triade_runtime.sh status  qué escucha el puerto, en qué modo y bajo
#                                     qué supervisor
#   scripts/triade_runtime.sh restart down + up
#
# Qué cambió y por qué: hasta el 2026-08-10 este guion arrancaba uvicorn con
# `setsid nohup` por su cuenta. Eso lo convertía en un segundo mecanismo de
# arranque compitiendo con las units de systemd que on_start.sh daba por buenas,
# y el proceso resultante no lo supervisaba nadie: al morir, no volvía. De ahí
# que Tríade sólo estuviera viva mientras hubiera una terminal abierta.
#
# Ahora la cadena es una sola y este guion es el cliente, no el dueño:
#
#   SERVICE MANAGER (systemd) -> triade-api.service -> apps.single_port_app:app
#
# El arranque productivo real lo hace systemd, tanto si lo pide una persona con
# `up` como si lo pide el arranque de la máquina. Es la misma ruta.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${TRIADE_STUDIO_PORT:-8010}"
URL="http://127.0.0.1:${PORT}"
UNIT="triade-api.service"

cd "$ROOT"
mkdir -p logs

listener_pid() { ss -lntpH "sport = :${PORT}" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2; }
listener_count() { ss -lntH "sport = :${PORT}" 2>/dev/null | grep -c . || true; }

up() {
  # Instalar es idempotente y barato, y es lo que hace que `up` funcione igual
  # en una máquina recién reiniciada, donde /etc/systemd/system viene vacío.
  bash "$ROOT/scripts/restore_file_modes.sh" >/dev/null || true
  bash "$ROOT/scripts/install_systemd_units.sh"

  sudo systemctl start triade-ollama.service || echo "aviso: ollama no arrancó; la API queda degradada"
  sudo systemctl start "$UNIT"
  sudo systemctl start triade-watchdog.service || true
  sudo systemctl start triade-backup.timer || true

  echo -n "app: esperando a ${URL}/health/live"
  for _ in $(seq 1 40); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${URL}/health/live")" = "200" ]; then
      echo " arriba"
      wait_for_workers
      status
      return
    fi
    echo -n "."
    sleep 3
  done
  echo " NO respondió a tiempo" >&2
  sudo systemctl status "$UNIT" --no-pager -l | head -20 >&2
  exit 1
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
  # `stop` a secas no basta: con Restart=always systemd lo levantaría otra vez en
  # cuanto el proceso saliera. Parar de verdad, a mano, es parar la unit.
  sudo systemctl stop "$UNIT" || true
  sudo systemctl stop triade-watchdog.service || true
  for _ in $(seq 1 15); do
    [ -z "$(listener_pid)" ] && break
    sleep 1
  done
  # Un huérfano de una era anterior (arrancado con nohup) no lo conoce systemd.
  local lpid; lpid="$(listener_pid)"
  if [ -n "$lpid" ]; then
    echo "puerto ${PORT} aún ocupado por pid ${lpid} fuera de systemd; se retira"
    kill "$lpid" 2>/dev/null || true
    sleep 2
    [ -n "$(listener_pid)" ] && kill -9 "$lpid" 2>/dev/null || true
  fi
  rm -f "$ROOT/logs/triade-runtime.pid"
  echo "app: parada (systemd no la relanzará hasta el próximo 'up')"
}

status() {
  echo "unit:      $(systemctl is-active "$UNIT" 2>/dev/null) / $(systemctl is-enabled "$UNIT" 2>/dev/null || echo 'no habilitada')"
  echo "reinicios: $(systemctl show -p NRestarts --value "$UNIT" 2>/dev/null || echo '?')"
  local lpid; lpid="$(listener_pid)"
  if [ -z "$lpid" ]; then
    echo "puerto ${PORT}: nada escuchando"
    return
  fi
  echo "puerto ${PORT}: pid ${lpid} ($(ps -o comm= -p "$lpid" 2>/dev/null)) unit=$(ps -o unit= -p "$lpid" 2>/dev/null | tr -d ' ')"
  echo "listeners en ${PORT}: $(listener_count) (debe ser 1)"
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
