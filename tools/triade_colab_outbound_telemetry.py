"""Run opt-in outbound Colab telemetry while the original runtime is alive.

No persistent credentials, no inbound tunnel, no shell execution, no raw memory
sent to Render. A user must start Colab; this module cannot start a kernel.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

INGEST_URL = "https://triade-omega-mcp.onrender.com/api/telemetry/ingest"
LOCAL = "http://127.0.0.1:8010"
_BOOL = ("runtime_enabled", "workers_active", "can_reason")
_STATS = (
    "cycles_last_24h",
    "missions_executed",
    "neuron_evidence_created",
    "candidates_created",
    "candidates_evaluated",
    "candidates_internally_checked",
    "candidates_verified_with_evidence",
    "candidates_consolidated",
    "candidates_rejected",
    "neurons_nourished",
)


def _get(path: str) -> dict[str, Any]:
    if path not in ("/health/live", "/api/runtime/heartbeat", "/api/runtime/learning-journal"):
        raise ValueError("non_allowlisted_local_path")
    headers = {"Accept": "application/json"}
    key = os.getenv("TRIADE_API_KEY", "").strip()
    if key:
        headers["X-Triade-Api-Key"] = key
    request = urllib.request.Request(LOCAL + path, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=7) as response:
        if response.status != 200:
            raise RuntimeError("local_runtime_unavailable")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise TypeError("invalid_local_response")
    return payload


def collect_once() -> dict[str, Any]:
    health = _get("/health/live")
    pulse = _get("/api/runtime/heartbeat")
    if health.get("status") != "ok" or pulse.get("api_server_alive") is not True:
        raise RuntimeError("original_runtime_not_healthy")
    observations: dict[str, Any] = {"api_server_alive": True}
    for key in _BOOL:
        value = pulse.get(key)
        if type(value) is bool:
            observations[key] = value
    cycle = pulse.get("heartbeat_cycle")
    if type(cycle) is int and 0 <= cycle <= 1_000_000_000:
        observations["heartbeat_cycle"] = cycle
    mode = pulse.get("mode")
    if (
        isinstance(mode, str)
        and 1 <= len(mode) <= 48
        and all(c.isascii() and (c.isalnum() or c in "-_") for c in mode)
    ):
        observations["mode"] = mode
    try:
        journal = _get("/api/runtime/learning-journal")
    except (urllib.error.URLError, ValueError, RuntimeError):
        journal = {}
    stats: dict[str, int] = {}
    for key in _STATS:
        value = journal.get(key)
        if type(value) is int and 0 <= value <= 1_000_000_000:
            stats[key] = value
    semantic = journal.get("semantic_documents_activity")
    if isinstance(semantic, dict):
        value = semantic.get("count")
        if type(value) is int and 0 <= value <= 1_000_000_000:
            stats["semantic_documents_count"] = value
    return {"schema_version": 1, "observations": observations, "stats": stats}


def send_once() -> dict[str, Any]:
    token = os.getenv("TRIADE_TELEMETRY_INGEST_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError("telemetry_secret_not_configured")
    report = collect_once()
    data = json.dumps(report, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        INGEST_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Bearer " + token,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=18) as response:
        if response.status != 200:
            raise RuntimeError("telemetry_not_accepted")
        ack = json.load(response)
    if ack.get("accepted") is not True or ack.get("certified") is not False:
        raise RuntimeError("telemetry_ack_unexpected")
    return {"submitted": True, "certified": False}


def run_while_colab_active(interval_seconds: int = 60) -> None:
    if not isinstance(interval_seconds, int) or not 30 <= interval_seconds <= 3600:
        raise ValueError("interval_must_be_30_to_3600_seconds")
    while True:
        try:
            send_once()
            print("Tríade: telemetría agregada enviada; no certificada")
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            # No token or raw API response must ever be logged.
            print("Tríade: telemetría no disponible (" + type(exc).__name__ + ")")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_while_colab_active()
