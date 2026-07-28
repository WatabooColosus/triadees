#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
studio_dir="$(cd "$repo_dir/.." && pwd)"
ollama_root="${TRIADE_STUDIO_OLLAMA_ROOT:-$studio_dir/.ollama}"
ollama_bin="$ollama_root/runtime/bin/ollama"
models_file="${1:-$repo_dir/config/studio-models.txt}"

export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export OLLAMA_MODELS="${OLLAMA_MODELS:-$ollama_root/models}"

installed="$($ollama_bin list | awk 'NR > 1 {print $1}')"
missing=0
while IFS= read -r model; do
  [[ -z "$model" || "$model" == \#* ]] && continue
  if grep -Fxq "$model" <<<"$installed"; then
    printf 'ok %s\n' "$model"
  else
    printf 'missing %s\n' "$model" >&2
    missing=1
  fi
done < "$models_file"
exit "$missing"
