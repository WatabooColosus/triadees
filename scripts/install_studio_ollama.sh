#!/usr/bin/env bash
set -euo pipefail

studio_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ollama_root="${TRIADE_STUDIO_OLLAMA_ROOT:-$studio_dir/.ollama}"
runtime_dir="$ollama_root/runtime"
ollama_bin="$runtime_dir/bin/ollama"
ollama_version="${TRIADE_STUDIO_OLLAMA_VERSION:-v0.32.5}"
user_bin_dir="$studio_dir/.local/bin"

if [[ -x "$ollama_bin" ]]; then
  mkdir -p "$user_bin_dir"
  ln -sfn "$ollama_bin" "$user_bin_dir/ollama"
  exit 0
fi

mkdir -p "$runtime_dir" "$ollama_root/models"
archive_url="https://github.com/ollama/ollama/releases/download/$ollama_version/ollama-linux-amd64.tar.zst"
curl --fail --location --silent --show-error "$archive_url" \
  | tar --zstd --extract --directory "$runtime_dir"
test -x "$ollama_bin"
mkdir -p "$user_bin_dir"
ln -sfn "$ollama_bin" "$user_bin_dir/ollama"
