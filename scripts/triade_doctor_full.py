#!/usr/bin/env python3
"""Tríade Ω · doctor --full

Comprehensive health check for the entire Tríade ecosystem.
Returns JSON and human-readable output.
"""
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path("/teamspace/studios/this_studio/triadees")
DB_PATH = REPO_ROOT / "triade/memory/triade.db"
ENV_FILE = Path("/etc/triade/triade.env")
PUBLIC_URL_TEMPLATE = "https://lightning.ai/agenciadigitalwataboo-org/deploy-model-project/studios/triade/web-ui?port={port}"

def sh(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, check=False)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1
    except OSError as e:
        # A single probe must not crash the whole doctor run.
        return str(e), -1

def check_ollama():
    out, rc = sh("curl -s --max-time 5 http://127.0.0.1:11434/api/tags", timeout=10)
    if rc != 0 or not out:
        return {"status": "CRITICAL", "detail": "Ollama not responding"}
    try:
        data = json.loads(out)
        models = [m["name"] for m in data.get("models", [])]
        return {
            "status": "HEALTHY",
            "models": models,
            "count": len(models),
            "detail": "Ollama responding",
        }
    except json.JSONDecodeError:
        return {"status": "CRITICAL", "detail": "Ollama returned invalid JSON"}

def check_inference():
    out, rc = sh(
        'curl -s --max-time 120 http://127.0.0.1:11434/api/generate '
        '-d \'{"model":"qwen2.5:3b-instruct","prompt":"Hi","stream":false}\'',
        timeout=120
    )
    if rc != 0 or not out:
        return {"status": "CRITICAL", "detail": "Inference failed"}
    try:
        data = json.loads(out)
        if data.get("done"):
            return {"status": "HEALTHY", "latency_ms": data.get("total_duration", 0) // 1_000_000}
        return {"status": "DEGRADED", "detail": "Inference incomplete"}
    except json.JSONDecodeError:
        return {"status": "CRITICAL", "detail": "Inference returned invalid JSON"}

def check_embedding():
    out, rc = sh(
        'curl -s --max-time 90 http://127.0.0.1:11434/api/embeddings '
        '-d \'{"model":"nomic-embed-text","prompt":"test"}\'',
        timeout=90
    )
    if rc != 0 or not out:
        return {"status": "DEGRADED", "detail": "Embedding failed"}
    try:
        data = json.loads(out)
        if "embedding" in data:
            return {"status": "HEALTHY", "dimensions": len(data["embedding"])}
        return {"status": "DEGRADED", "detail": "No embedding in response"}
    except json.JSONDecodeError:
        return {"status": "DEGRADED", "detail": "Embedding returned invalid JSON"}

def check_api():
    for endpoint in ["/health/live", "/api/health"]:
        out, rc = sh(f"curl -s --max-time 5 http://127.0.0.1:8010{endpoint}")
        if rc == 0 and out:
            try:
                data = json.loads(out)
                if "status" in data or "alive" in str(data):
                    return {"status": "HEALTHY", "endpoint": endpoint}
            except json.JSONDecodeError:
                pass
    return {"status": "CRITICAL", "detail": "API not responding"}

def check_ollama_blood():
    out, rc = sh("curl -s --max-time 10 http://127.0.0.1:8010/api/models/ollama/blood")
    if rc != 0 or not out:
        return {"status": "DEGRADED", "detail": "Blood endpoint not responding"}
    try:
        data = json.loads(out)
        if data.get("status") == "ok":
            return {"status": "HEALTHY", "blood_status": data.get("ollama_blood", {}).get("mode")}
        return {"status": "DEGRADED", "detail": data.get("message", "unknown")}
    except json.JSONDecodeError:
        return {"status": "DEGRADED", "detail": "Invalid blood endpoint response"}

def check_heartbeat():
    out, rc = sh(
        "curl -s --max-time 30 http://127.0.0.1:8010/api/runtime/heartbeat",
        timeout=30
    )
    if rc != 0 or not out:
        return {"status": "DEGRADED", "detail": "Heartbeat not responding"}
    try:
        json.loads(out)
        return {"status": "HEALTHY", "detail": "Pulse active"}
    except json.JSONDecodeError:
        return {"status": "DEGRADED", "detail": "Invalid heartbeat response"}

def check_database():
    if not DB_PATH.exists():
        return {"status": "CRITICAL", "detail": "Database file not found"}
    out, _rc = sh(f'python3 -c "import sqlite3; c=sqlite3.connect(\'{DB_PATH}\').cursor(); c.execute(\'PRAGMA integrity_check\'); print(c.fetchone()[0])"')
    if "ok" in out.lower():
        return {"status": "HEALTHY", "size_mb": round(DB_PATH.stat().st_size / 1_048_576, 1)}
    return {"status": "CRITICAL", "detail": f"Integrity check: {out[:100]}"}

def check_identity():
    out, _rc = sh(f'python3 -c "import sqlite3; c=sqlite3.connect(\'{DB_PATH}\').cursor(); c.execute(\'SELECT COUNT(*) FROM identity_core\'); print(c.fetchone()[0])"')
    try:
        count = int(out)
        if count >= 6:
            return {"status": "HEALTHY", "rows": count}
        return {"status": "DEGRADED", "rows": count, "detail": "Identity core may be incomplete"}
    except ValueError:
        return {"status": "CRITICAL", "detail": "Cannot read identity_core"}

def check_git():
    out, rc = sh("git rev-parse HEAD 2>/dev/null", timeout=5)
    sha = out.strip() if rc == 0 else "unknown"
    out2, _rc2 = sh("git status --porcelain 2>/dev/null", timeout=5)
    dirty = bool(out2.strip())
    return {"status": "HEALTHY", "sha": sha[:12] if len(sha) > 12 else sha, "dirty": dirty}

def check_systemd(name):
    out, _rc = sh(f"systemctl is-active {name} 2>/dev/null")
    return out.strip() == "active"

def check_public_url():
    port = "8010"
    url = PUBLIC_URL_TEMPLATE.format(port=port)
    out, rc = sh(f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 10 '{url}'")
    if rc == 0 and out.strip().startswith("2"):
        return {"status": "HEALTHY", "url": url}
    return {"status": "DEGRADED", "url": url, "detail": f"HTTP {out[:10]}"}

def check_backup():
    backup_dir = REPO_ROOT / "artifacts/backups"
    if not backup_dir.exists():
        return {"status": "DEGRADED", "detail": "No backup directory"}
    backups = sorted(backup_dir.glob("triade-*.db.gz.fernet"), key=lambda f: f.stat().st_mtime, reverse=True)
    if backups:
        newest = max(backups, key=lambda f: f.stat().st_mtime)
        age_h = (time.time() - newest.stat().st_mtime) / 3600
        return {"status": "HEALTHY" if age_h < 48 else "DEGRADED", "latest_backup": newest.name, "age_hours": round(age_h, 1)}
    return {"status": "DEGRADED", "detail": "No backup files found"}

def check_disk():
    out, rc = sh("df -h /teamspace/studios/this_studio/triadees")
    if rc == 0:
        lines = out.split("\n")
        for line in lines:
            if "/teamspace" in line or "overlay" in line:
                parts = line.split()
                if len(parts) >= 5:
                    return {"status": "HEALTHY", "free": parts[3], "used_pct": parts[4]}
    return {"status": "UNKNOWN", "detail": "Cannot read disk"}

def check_ram():
    out, rc = sh("free -h | grep 'Mem:'")
    if rc == 0 and out:
        parts = out.split()
        return {"status": "HEALTHY", "total": parts[1], "available": parts[6]}
    return {"status": "UNKNOWN", "detail": "Cannot read RAM"}

def check_gpu():
    out, rc = sh("nvidia-smi --query-gpu=name,memory.free --format=csv,noheader 2>/dev/null")
    if rc == 0 and out:
        return {"status": "HEALTHY", "detail": out.strip()}
    return {"status": "DEGRADED", "detail": "No GPU access"}

def check_systemd_units():
    services = ["triade-ollama.service", "triade-api.service", "triade-watchdog.service"]
    timers = ["triade-backup.timer"]
    results = {}
    all_ok = True
    for u in services:
        ok = check_systemd(u)
        results[u] = "active" if ok else "inactive"
        if not ok:
            all_ok = False
    for u in timers:
        out, _rc = sh(f"systemctl is-enabled {u} 2>/dev/null")
        ok = out.strip() == "enabled"
        results[u] = "enabled" if ok else "disabled"
        if not ok:
            all_ok = False
    return {"status": "HEALTHY" if all_ok else "DEGRADED", "units": results}

def main():
    results = {
        "timestamp": datetime.now(UTC).isoformat(),
        "host": os.uname().nodename,
        "sha": check_git()["sha"],
        "checks": {},
    }

    checks = [
        ("repository", check_git),
        ("database", check_database),
        ("identity", check_identity),
        ("ollama", check_ollama),
        ("inference", check_inference),
        ("embedding", check_embedding),
        ("ollama_blood", check_ollama_blood),
        ("api", check_api),
        ("heartbeat", check_heartbeat),
        ("public_url", check_public_url),
        ("systemd", check_systemd_units),
        ("backup", check_backup),
        ("disk", check_disk),
        ("ram", check_ram),
        ("gpu", check_gpu),
    ]

    status_order = {"CRITICAL": 0, "DEGRADED": 1, "UNKNOWN": 2, "RECOVERING": 3, "HEALTHY": 4, "active": 4}

    for name, fn in checks:
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 -- one failing probe must not abort the other 14
            result = {"status": "UNKNOWN", "detail": str(e)}
        results["checks"][name] = result

    # Overall status
    statuses = [c["status"] for c in results["checks"].values()]
    min_status = min(statuses, key=lambda s: status_order.get(s, 99))
    results["overall_status"] = min_status

    # Summary of non-healthy
    degraded = []
    for name, c in results["checks"].items():
        if c["status"] not in ("HEALTHY", "active"):
            degraded.append(f"{name}={c['status']}")
    results["degraded_components"] = degraded

    if "--json" in sys.argv:
        print(json.dumps(results, indent=2))
    else:
        print(f"\n{'='*60}")
        print("  Tríade Ω · doctor --full")
        print(f"  Host: {results['host']}")
        print(f"  SHA: {results['sha']}")
        print(f"  Time: {results['timestamp']}")
        print(f"  Status: {results['overall_status']}")
        print(f"{'='*60}")
        for name, c in results["checks"].items():
            status = c["status"]
            icon = {"HEALTHY": "✓", "DEGRADED": "⚠", "CRITICAL": "✗", "UNKNOWN": "?"}.get(status, "?")
            detail = c.get("detail", c.get("free", c.get("available", "")))
            print(f"  {icon} {name}: {status}".ljust(50) + f" {detail[:60]}")
        if degraded:
            print(f"\n  ⚠ Degraded/Critical: {len(degraded)}")
            for d in degraded:
                print(f"    - {d}")
        print()

    return 0 if results["overall_status"] in ("HEALTHY", "DEGRADED") else 1

if __name__ == "__main__":
    sys.exit(main())
