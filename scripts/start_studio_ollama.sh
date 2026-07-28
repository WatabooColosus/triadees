#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
studio_dir="$(cd "$repo_dir/.." && pwd)"
ollama_root="${TRIADE_STUDIO_OLLAMA_ROOT:-$studio_dir/.ollama}"
ollama_bin="$ollama_root/runtime/bin/ollama"
models_file="${TRIADE_STUDIO_MODELS_FILE:-$repo_dir/config/studio-models.txt}"
log_dir="$repo_dir/logs"
pid_file="$log_dir/studio-ollama.pid"

"$repo_dir/scripts/install_studio_ollama.sh"
mkdir -p "$log_dir" "$ollama_root/models"

export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$ollama_root/models}"
export OLLAMA_MAX_LOADED_MODELS="${OLLAMA_MAX_LOADED_MODELS:-1}"
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-1}"

if ! curl --fail --silent --max-time 2 "http://$OLLAMA_HOST/api/tags" >/dev/null; then
  nohup "$ollama_bin" serve >"$log_dir/studio-ollama.log" 2>&1 &
  printf '%s\n' "$!" > "$pid_file"
fi

for _ in {1..60}; do
  if curl --fail --silent --max-time 2 "http://$OLLAMA_HOST/api/tags" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent --max-time 2 "http://$OLLAMA_HOST/api/tags" >/dev/null

# Reconcile the declared catalog after every Studio restart. Existing blobs are
# reused, and missing models are restored without delaying the web startup.
nohup "$repo_dir/scripts/ensure_studio_models.sh" "$models_file" \
  >"$log_dir/studio-model-sync.log" 2>&1 &
