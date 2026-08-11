#!/usr/bin/env bash
# Instala (o refresca) las units de Tríade en systemd y las deja habilitadas.
#
# Por qué hace falta reinstalarlas en cada arranque y no basta con `enable` una
# vez: en este Studio la raíz es un overlay de contenedor y sólo persiste
# /teamspace/studios/this_studio. `/etc/systemd/system` se recrea vacío cada vez
# que el Studio arranca, así que una unit habilitada ayer no existe hoy. El
# 2026-08-10 se comprobó: cero units `triade*` instaladas, nada escuchando en el
# 8010, y `on_start.sh` afirmando en su cabecera que «las units ya arrancan solas
# por boot». No arrancaban: no existían.
#
# La fuente de verdad son los ficheros de deploy/systemd/ del repo, que sí
# persisten. Este script es idempotente: se puede llamar en cada arranque.
#
# Dos cosas que NO hace, a propósito:
#   - No instala triade-workers.service. Los workers ya corren dentro del proceso
#     de la API (`start_workers_if_configured` en el lifespan de
#     apps/single_port_app.py, con TRIADE_WORKERS_AUTOSTART=true). Una unit
#     aparte sería un segundo pool de workers sobre la misma base.
#   - No mata procesos a ciegas para liberar el 8010. Identifica al dueño y sólo
#     retira huérfanos sin supervisar, porque el fallo clásico aquí es el
#     contrario: un `nohup` manual gana la carrera por el puerto y deja a la unit
#     de systemd reiniciándose en bucle mientras sirve tráfico un proceso que
#     nadie supervisa (observado el 2026-07-30, 150+ reinicios de triade-ollama).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_SRC="$ROOT/deploy/systemd"
UNIT_DST="/etc/systemd/system"
PORT="${TRIADE_STUDIO_PORT:-8010}"

# Units que gobierna este instalador. El orden importa sólo para la lectura.
UNITS=(
    triade-ollama.service
    triade-api.service
    triade-watchdog.service
    triade-backup.service
    triade-backup.timer
)
# Habilitadas al arranque (backup.service lo dispara su timer, no el boot).
ENABLE=(
    triade-ollama.service
    triade-api.service
    triade-watchdog.service
    triade-backup.timer
)
# Units retiradas: si quedaron instaladas de una versión anterior, se van.
RETIRED=(
    triade-workers.service
)

log() { echo "[install-units] $*"; }

if [ ! -d "$UNIT_SRC" ]; then
    log "no existe $UNIT_SRC; nada que instalar" >&2
    exit 1
fi

# El .env vive en el repo (persiste) y trae secretos, por eso no está en git.
# Las units lo cargan con EnvironmentFile. Si falta, systemd rechaza la unit.
if [ ! -f "$ROOT/.env" ]; then
    log "AVISO: falta $ROOT/.env; las units arrancarán sin su configuración"
fi

changed=0
for unit in "${UNITS[@]}"; do
    src="$UNIT_SRC/$unit"
    if [ ! -f "$src" ]; then
        log "AVISO: $unit no está en deploy/systemd, se omite"
        continue
    fi
    if ! sudo cmp -s "$src" "$UNIT_DST/$unit" 2>/dev/null; then
        sudo install -m 0644 "$src" "$UNIT_DST/$unit"
        changed=1
        log "instalada $unit"
    fi
done

for unit in "${RETIRED[@]}"; do
    if [ -f "$UNIT_DST/$unit" ]; then
        sudo systemctl disable --now "$unit" >/dev/null 2>&1 || true
        sudo rm -f "$UNIT_DST/$unit"
        changed=1
        log "retirada $unit (los workers corren dentro de la API)"
    fi
done

if [ "$changed" = "1" ]; then
    sudo systemctl daemon-reload
    log "daemon-reload hecho"
fi

for unit in "${ENABLE[@]}"; do
    sudo systemctl enable "$unit" >/dev/null 2>&1 || log "AVISO: no se pudo habilitar $unit"
done
log "habilitadas: ${ENABLE[*]}"

# Un huérfano sin supervisar en el puerto deja a la unit en bucle de reinicio.
# Se retira sólo si nadie lo supervisa: si el dueño ya es la unit, no se toca.
#
# Se vigilan los dos puertos, no sólo el de la API: el incidente del 2026-07-30
# —150+ reinicios de triade-ollama.service mientras el tráfico lo servía un
# `nohup ollama serve` manual— fue justamente en el 11434.
listener_pid() {
    ss -lntpH "sport = :${1}" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2
}

# La pertenencia se decide por el cgroup del proceso, no por `ps -o unit=`, que
# no está disponible en todos los procps y devuelve vacío sin avisar.
owner_unit() {
    sed -n 's/.*\/\([a-z0-9@._-]*\.service\)$/\1/p' "/proc/${1}/cgroup" 2>/dev/null | head -1
}

free_port_from_orphan() {
    port="$1"
    expected_unit="$2"
    lpid="$(listener_pid "$port" || true)"
    [ -n "$lpid" ] || return 0

    owner="$(owner_unit "$lpid")"
    if [ "$owner" = "$expected_unit" ]; then
        log "puerto $port: ya lo sirve $expected_unit (pid $lpid), no se toca"
        return 0
    fi

    log "puerto $port: huérfano sin supervisar (pid $lpid, unit='${owner:-ninguna}'), se retira"
    kill "$lpid" 2>/dev/null || true
    for _ in $(seq 1 10); do
        sleep 1
        [ -z "$(listener_pid "$port" || true)" ] && break
    done
    # El runtime completo no siempre cierra con SIGTERM: libera el puerto pero
    # los hilos de fondo siguen vivos. Se remata sólo si sigue ahí.
    if [ -n "$(listener_pid "$port" || true)" ]; then
        kill -9 "$lpid" 2>/dev/null || true
        sleep 1
    fi
}

free_port_from_orphan "$PORT" "triade-api.service"
free_port_from_orphan "11434" "triade-ollama.service"

log "listo"
