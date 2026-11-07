"""Bounded, ephemeral Colab telemetry relay.

Colab *pushes* aggregate observations through an independent ingest token.
No database, private memory, raw logs or runtime execution is exposed.
"""

from __future__ import annotations

import hmac
import json
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

MAX_BYTES = 4096
FRESH_SECONDS = 300
_MAX_COUNT = 1_000_000_000
_BOOL_FIELDS = frozenset(
    {"api_server_alive", "runtime_enabled", "workers_active", "can_reason"}
)
_INT_FIELDS = frozenset({"heartbeat_cycle"})
_STATS_FIELDS = frozenset(
    {
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
        "semantic_documents_count",
    }
)
_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_lock = threading.Lock()
_last: dict[str, Any] | None = None
_last_clock: float = 0


def _reject(status: int, reason: str) -> JSONResponse:
    return JSONResponse({"error": reason}, status_code=status, headers=_HEADERS)


def _ingest_access(request: Request) -> int | None:
    expected = os.getenv("TRIADE_TELEMETRY_INGEST_TOKEN", "").strip()
    if len(expected) < 32:
        return 503
    scheme, separator, supplied = request.headers.get("authorization", "").partition(
        " "
    )
    if (
        not separator
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(supplied, expected)
    ):
        return 401
    return None


def _validate_payload(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != {
        "schema_version",
        "observations",
        "stats",
    }:
        raise ValueError("invalid_structure")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("invalid_version")
    obs, stats = data["observations"], data["stats"]
    if not isinstance(obs, dict) or not isinstance(stats, dict):
        raise TypeError("invalid_fields")
    if not obs or not set(obs) <= (_BOOL_FIELDS | _INT_FIELDS | {"mode"}):
        raise ValueError("invalid_observations")
    if not set(stats) <= _STATS_FIELDS:
        raise ValueError("invalid_stats")
    cleaned_obs: dict[str, Any] = {}
    for name, value in obs.items():
        valid_bool = name in _BOOL_FIELDS and type(value) is bool
        valid_int = name in _INT_FIELDS and type(value) is int and 0 <= value <= _MAX_COUNT
        valid_mode = (
            name == "mode"
            and isinstance(value, str)
            and 1 <= len(value) <= 48
            and all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in value)
        )
        if not (valid_bool or valid_int or valid_mode):
            raise ValueError("invalid_observation_type")
        cleaned_obs[name] = value
    cleaned_stats: dict[str, int] = {}
    for name, value in stats.items():
        if type(value) is not int or not 0 <= value <= _MAX_COUNT:
            raise ValueError("invalid_stat_type")
        cleaned_stats[name] = value
    return {"observations": cleaned_obs, "stats": cleaned_stats}


def _store(data: dict[str, Any]) -> None:
    global _last, _last_clock
    with _lock:
        _last = {
            "received_at_utc": datetime.now(UTC).isoformat(),
            "source": "authenticated_colab_telemetry",
            "runtime_original_conectado": None,
            "runtime_identity_certified": False,
            "full_runtime_verified": False,
            "full_learning_certified": False,
            "writes_enabled": False,
            **data,
        }
        _last_clock = time.monotonic()


def _snapshot() -> dict[str, Any]:
    with _lock:
        if _last is None:
            return {
                "status": "no_reports",
                "fresh": False,
                "full_runtime_verified": False,
                "full_learning_certified": False,
            }
        age = max(0, int(time.monotonic() - _last_clock))
        if age >= FRESH_SECONDS:
            return {
                "status": "stale",
                "fresh": False,
                "received_at_utc": _last["received_at_utc"],
                "age_seconds": age,
                "full_runtime_verified": False,
                "full_learning_certified": False,
            }
        return {"status": "fresh", "fresh": True, "age_seconds": age, **_last}


def attach_telemetry_routes(
    app: Any, operator_check: Callable[[Request], bool]
) -> Any:
    async def ingest(request: Request) -> JSONResponse:
        denied = _ingest_access(request)
        if denied is not None:
            return _reject(denied, "ingest_unauthorized" if denied == 401 else "ingest_disabled")
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            return _reject(415, "content_type_invalid")
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_BYTES:
            return _reject(413, "payload_too_large")
        buffer = bytearray()
        async for fragment in request.stream():
            if len(buffer) + len(fragment) > MAX_BYTES:
                return _reject(413, "payload_too_large")
            buffer.extend(fragment)
        try:
            report = _validate_payload(json.loads(buffer))
        except (ValueError, TypeError, UnicodeDecodeError):
            return _reject(400, "payload_invalid")
        _store(report)
        return JSONResponse({"accepted": True, "certified": False}, headers=_HEADERS)

    async def snapshot(request: Request) -> JSONResponse:
        try:
            operator_check(request)
        except HTTPException as exc:
            return _reject(exc.status_code, "operator_unavailable" if exc.status_code == 503 else "operator_unauthorized")
        return JSONResponse(_snapshot(), headers=_HEADERS)

    app.routes.extend(
        [
            Route("/api/telemetry/ingest", ingest, methods=["POST"]),
            Route("/api/private/telemetry", snapshot, methods=["GET"]),
        ]
    )
    return app
