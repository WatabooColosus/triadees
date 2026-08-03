#!/usr/bin/env bash
set -u
ROOT="${TRIADE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="${TRIADE_STATE_DIR:-$ROOT/.runtime/unidad01}"
HOST="${TRIADE_HOST:-127.0.0.1}"
API_PORT="${TRIADE_API_PORT:-8010}"
MODEL_PORT="${TRIADE_MODEL_PORT:-11434}"

printf '=== Unidad 01 / Tríade ===\n'
printf 'Host: %s\n' "$(hostname)"
printf 'Fecha: %s\n' "$(date -Iseconds)"

printf '\nServicios:\n'
for unit in triade.service triade-api.service triade-chat-ui.service triade-model-router.service ollama.service; do
  if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q "^$unit"; then
    printf '%-34s %s\n' "$unit" "$(systemctl is-active "$unit" 2>/dev/null || true)"
  fi
done

printf '\nPuertos:\n'
ss -lntp 2>/dev/null | grep -E ":(${API_PORT}|${MODEL_PORT})\\b" || true

printf '\nSalud API:\n'
healthy=0
for path in /health /api/health /healthz /; do
  if curl -fsS --max-time 3 "http://$HOST:$API_PORT$path" >/dev/null 2>&1; then
    printf 'OK http://%s:%s%s\n' "$HOST" "$API_PORT" "$path"
    healthy=1
    break
  fi
done

printf '\nModelo:\n'
if curl -fsS --max-time 3 "http://$HOST:$MODEL_PORT/api/tags" >/dev/null 2>&1; then
  printf 'OK runtime de modelos\n'
else
  printf 'NO CONFIRMADO runtime de modelos\n'
fi

if [ -f "$STATE_DIR/activation-report.json" ]; then
  printf '\nÚltimo reporte:\n'
  cat "$STATE_DIR/activation-report.json"
  printf '\n'
fi

exit $((healthy == 1 ? 0 : 1))
