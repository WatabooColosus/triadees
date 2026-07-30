#!/bin/bash
# Tríade Ω · Auto-start after Lightning Studio reboot
# This script runs every time the Studio starts.
#
# Systemd (triade-ollama, triade-api, triade-workers, triade-watchdog) is the
# single source of truth for process supervision: units are `enabled`, so they
# already start on boot via multi-user.target with Restart=always. This script
# must NOT start those processes manually with nohup — a manual process and a
# systemd unit racing for the same port leaves the systemd unit stuck in an
# infinite crash-restart loop while an unsupervised orphan actually serves
# traffic (observed 2026-07-30: triade-ollama.service crash-looped 150+ times
# post-reboot because a manual `nohup ollama serve` from this script won the
# port race). `systemctl start` is idempotent, so it is always safe to call.

REPO_DIR="/teamspace/studios/this_studio/triadees"
LOG_DIR="$REPO_DIR/logs"
OLLAMA_BIN="/teamspace/studios/this_studio/.ollama/runtime/bin/ollama"
OLLAMA_ROOT="/teamspace/studios/this_studio/.ollama"
PORT=8010

mkdir -p "$LOG_DIR" "$OLLAMA_ROOT/models"

export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$OLLAMA_ROOT/models}"
export CUDA_VISIBLE_DEVICES="0"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-3}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-4}"
export PYTHONUNBUFFERED=1

start_via_systemd_or_fallback() {
    unit="$1"
    fallback_cmd="$2"
    log_file="$3"

    if systemctl list-unit-files "$unit" >/dev/null 2>&1 && systemctl list-unit-files "$unit" | grep -q "$unit"; then
        sudo systemctl start "$unit" >>"$LOG_DIR/on_start_systemd.log" 2>&1
    else
        # Bootstrap fallback: no systemd unit installed yet for this service.
        nohup bash -c "$fallback_cmd" >"$log_file" 2>&1 &
    fi
}

# 1. Ollama — prefer systemd; fall back to nohup only if the unit is missing.
start_via_systemd_or_fallback \
    "triade-ollama.service" \
    "'$OLLAMA_BIN' serve" \
    "$LOG_DIR/studio-ollama.log"

for i in $(seq 1 60); do
    curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
done

# 2. Ensure required models (idempotent, not process supervision — no race).
MODELS_FILE="$REPO_DIR/config/studio-models.txt"
if [ -f "$MODELS_FILE" ] && curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    nohup "$REPO_DIR/scripts/ensure_studio_models.sh" "$MODELS_FILE" \
        >"$LOG_DIR/studio-model-sync.log" 2>&1 &
fi

# 3. API — prefer systemd; fall back to nohup only if the unit is missing.
start_via_systemd_or_fallback \
    "triade-api.service" \
    "cd '$REPO_DIR' && python -m uvicorn apps.single_port_app:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'" \
    "$LOG_DIR/studio-web.log"

# 4. Workers / watchdog — systemd-only, enabled units already start on boot.
#    Idempotent nudge in case the unit files were installed after boot.
for unit in triade-workers.service triade-watchdog.service; do
    if systemctl list-unit-files "$unit" 2>/dev/null | grep -q "$unit"; then
        sudo systemctl start "$unit" >>"$LOG_DIR/on_start_systemd.log" 2>&1
    fi
done

# 5. Run verification (read-mostly; safe to run every boot).
nohup bash "$REPO_DIR/scripts/post_reboot_verify.sh" \
    >"$LOG_DIR/post-reboot-verify.log" 2>&1 &
