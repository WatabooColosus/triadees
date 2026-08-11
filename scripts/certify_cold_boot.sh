#!/usr/bin/env bash
# Reproduce el arranque en frío sin reiniciar la máquina.
#
# Reiniciar el host desde dentro del entorno de trabajo no es seguro —se lleva
# por delante la sesión—, así que la prueba de boot completa queda sin ejecutar
# y se dice. Lo que sí se puede reproducir es exactamente lo que el reinicio le
# hace a Tríade, que es lo que la mataba:
#
#   la raíz del contenedor es un overlay y /etc/systemd/system vuelve vacío.
#
# Eso es lo que esta prueba provoca a propósito: retira las units, recarga
# systemd para que se olvide de ellas, deja el organismo parado, y a partir de
# ahí ejecuta el MISMO guion que corre en el arranque real (on_start.sh) sin
# tocar nada a mano. Si Tríade vuelve al 8010, la cadena de arranque funciona.
#
# Lo que esta prueba NO demuestra: que el propio Lightning Studio invoque
# on_start.sh al arrancar. Eso lo garantiza la plataforma y el fichero está en
# su sitio (~/.lightning_studio/on_start.sh), pero aquí no se comprueba.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${TRIADE_STUDIO_PORT:-8010}"
URL="http://127.0.0.1:${PORT}"
OUT="${1:-$ROOT/artifacts/always_on/cold-boot.json}"

cd "$ROOT"
mkdir -p "$(dirname "$OUT")"

listeners() { ss -lntH "sport = :${PORT}" 2>/dev/null | grep -c . || true; }
now() { date -Is; }

echo "== 1. Estado previo"
before_listeners="$(listeners)"
echo "   listeners en $PORT: $before_listeners"

echo "== 2. Simular la recreación del contenedor: parar y borrar las units"
sudo systemctl stop triade-api.service triade-watchdog.service triade-ollama.service 2>/dev/null
sudo systemctl disable triade-api.service triade-watchdog.service triade-ollama.service triade-backup.timer >/dev/null 2>&1
sudo rm -f /etc/systemd/system/triade-*.service /etc/systemd/system/triade-*.timer
sudo systemctl daemon-reload
units_left="$(systemctl list-unit-files 'triade*' --no-pager 2>/dev/null | grep -c 'triade' || true)"
echo "   units triade* instaladas tras el borrado: $units_left"

for _ in $(seq 1 20); do
    [ "$(listeners)" = "0" ] && break
    sleep 1
done
echo "   listeners en $PORT tras parar: $(listeners)"

cold_at="$(now)"
start_epoch="$(date +%s)"

echo "== 3. Ejecutar el arranque real, sin ayudarlo"
bash "$ROOT/deploy/lightning_studio/on_start.sh"

echo "== 4. Esperar a que el organismo vuelva solo"
healthy_at=""
for _ in $(seq 1 60); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${URL}/health/live")" = "200" ]; then
        healthy_at="$(now)"
        break
    fi
    sleep 3
done
recovery_seconds=$(( $(date +%s) - start_epoch ))

workers_active=false
for _ in $(seq 1 40); do
    if curl -s --max-time 20 "${URL}/api/runtime/heartbeat" 2>/dev/null \
        | python -c 'import sys,json;sys.exit(0 if json.load(sys.stdin).get("workers_active") else 1)' 2>/dev/null; then
        workers_active=true
        break
    fi
    sleep 5
done

echo "== 5. Veredicto"
python - "$OUT" "$cold_at" "$healthy_at" "$recovery_seconds" "$workers_active" "$units_left" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

from triade.runtime.service_supervision import build_service_supervision

out, cold_at, healthy_at, recovery, workers, units_left = sys.argv[1:7]
supervision = build_service_supervision()

enabled = subprocess.run(
    ["systemctl", "is-enabled", "triade-api.service"],
    capture_output=True, text=True, check=False,
).stdout.strip()

checks = {
    "units_were_removed": units_left == "0",
    "came_back_without_manual_start": bool(healthy_at),
    "url_restored": supervision.get("listener_count") == 1,
    "single_listener": supervision.get("listener_state") == "healthy",
    "service_managed": bool(supervision.get("service_managed")),
    "autostart_reenabled": enabled == "enabled",
    "workers_recovered": workers == "true",
}
report = {
    "test": "cold_boot_simulation",
    "note": (
        "Reproduce la pérdida de /etc/systemd/system que provoca la recreación "
        "del contenedor, y arranca con el mismo guion que el boot real. "
        "HOST_REBOOT_TEST queda NOT_EXECUTED: reiniciar el host desde el "
        "entorno de trabajo se lleva la sesión."
    ),
    "host_reboot_test": "NOT_EXECUTED",
    "host_reboot_test_reason": (
        "reiniciar la máquina desde dentro del entorno destruiría la sesión de "
        "trabajo; no se finge la prueba"
    ),
    "cold_at": cold_at,
    "healthy_at": healthy_at or None,
    "recovery_seconds": int(recovery),
    "units_installed_after_removal": units_left,
    "supervision_after": supervision,
    "checks": checks,
    "verdict": "CERTIFIED" if all(checks.values()) else "FAILED",
    "failed_checks": [k for k, v in checks.items() if not v],
}
Path(out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: report[k] for k in ("verdict", "failed_checks", "recovery_seconds", "checks")},
                 indent=2, ensure_ascii=False))
print(f"informe: {out}")
PY
