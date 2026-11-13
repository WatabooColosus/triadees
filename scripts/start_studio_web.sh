#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${TRIADE_STUDIO_PORT:-8010}"
log_dir="$repo_dir/logs"
pid_file="$log_dir/studio-web.pid"

mkdir -p "$log_dir"

if [[ -f "$pid_file" ]]; then
  existing_pid="$(<"$pid_file")"
  if [[ "$existing_pid" =~ ^[0-9]+$ ]] && kill -0 "$existing_pid" 2>/dev/null; then
    exit 0
  fi
fi

cd "$repo_dir"
nohup python -m uvicorn apps.single_port_app:app \
  --host 0.0.0.0 \
  --port "$port" \
  --proxy-headers \
  --forwarded-allow-ips='*' \
  >"$log_dir/studio-web.log" 2>&1 &
web_pid=$!
printf '%s\n' "$web_pid" > "$pid_file"

for _ in {1..60}; do
  if curl --fail --silent --show-error --max-time 2 "http://127.0.0.1:$port/health/live" >/dev/null; then
    exit 0
  fi
  if ! kill -0 "$web_pid" 2>/dev/null; then
    exit 1
  fi
  sleep 1
done

exit 1
