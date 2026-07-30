"""Monitor de duración wall-clock real para web, Ollama y SQLite."""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any


def run_wall_clock_validation(
    *,
    duration_seconds: int,
    interval_seconds: int,
    db_path: str | Path,
    web_url: str,
    ollama_url: str,
) -> dict[str, Any]:
    if duration_seconds < 1 or interval_seconds < 1:
        raise ValueError("duration_and_interval_must_be_positive_real_seconds")
    started_wall = time.time()
    started = time.monotonic()
    checks: list[dict[str, Any]] = []
    while True:
        now = time.monotonic()
        web_ok = _http_ok(web_url)
        ollama_ok = _http_ok(ollama_url)
        with sqlite3.connect(db_path, timeout=5) as conn:
            integrity = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        checks.append(
            {
                "elapsed_seconds": round(now - started, 3),
                "web_ok": web_ok,
                "ollama_ok": ollama_ok,
                "db_integrity": integrity,
            }
        )
        remaining = duration_seconds - (time.monotonic() - started)
        if remaining <= 0:
            break
        time.sleep(min(interval_seconds, remaining))
    elapsed = time.monotonic() - started
    passed = sum(
        item["web_ok"] and item["ollama_ok"] and item["db_integrity"] == "ok"
        for item in checks
    )
    availability = passed / len(checks)
    return {
        "requested_duration_seconds": duration_seconds,
        "elapsed_seconds": elapsed,
        "wall_clock_not_compressed": elapsed >= duration_seconds,
        "started_at_epoch": started_wall,
        "checks": checks,
        "availability": availability,
        "db_corruption": sum(item["db_integrity"] != "ok" for item in checks),
        "passed": elapsed >= duration_seconds and availability >= 0.99,
    }


def write_report(report: dict[str, Any], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return 200 <= response.status < 300
    except OSError:
        return False
