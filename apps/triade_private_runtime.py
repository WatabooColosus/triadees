"""Read-only, bearer-authenticated access to an external Tríade runtime.

This module is mounted only under /api/private/* on the tablet web app.
Nothing is enabled automatically: a long operator token and an upstream HTTPS
URL must be configured out-of-band. Tokens are never returned or persisted.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from apps import chatgpt_actions_app as runtime_gateway

_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_SCALARS = (
    "since_hours",
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


def _reject(status_code: int, error: str) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status_code, headers=_HEADERS)


def _authorized(request: Request) -> bool:
    expected = os.getenv("TRIADE_ACTIONS_TOKEN", "").strip()
    # Do not expose a remotely guessable, short operator secret.
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="private_access_not_configured")
    auth = request.headers.get("authorization", "")
    scheme, separator, candidate = auth.partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(candidate, expected)
    ):
        raise HTTPException(status_code=401, detail="invalid_operator_token")
    return True


def _upstream_ready() -> bool:
    try:
        runtime_gateway._upstream_url()
    except HTTPException:
        return False
    return True


def _summary_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    """Use a fixed allowlist matching triade.core.learning_journal.

    Never return recent events, lesson texts, queue titles, source references,
    memory records or arbitrary dict/string keys from the upstream response.
    """
    result: dict[str, Any] = {}
    for key in _SCALARS:
        number = raw.get(key)
        if type(number) is int and 0 <= number <= 1_000_000_000:
            result[key] = number
    semantic = raw.get("semantic_documents_activity")
    if isinstance(semantic, dict):
        count = semantic.get("count")
        if type(count) is int and 0 <= count <= 1_000_000_000:
            result["semantic_documents_count"] = count
    return result


def _runtime_status() -> dict[str, Any]:
    live = runtime_gateway._upstream("GET", "/health/live")
    pulse = runtime_gateway._upstream("GET", "/api/runtime/heartbeat")
    allowed_bool = ("runtime_enabled", "workers_active", "can_reason", "fallback_mode")
    observations = {
        name: pulse[name] for name in allowed_bool if type(pulse.get(name)) is bool
    }
    for name in ("heartbeat_cycle", "heartbeat_age_ms"):
        value = pulse.get(name)
        if type(value) is int and 0 <= value <= 1_000_000_000_000:
            observations[name] = value
    mode = pulse.get("mode")
    if isinstance(mode, str) and 0 < len(mode) <= 60:
        observations["mode"] = mode
    # Distinguish HTTP connectivity from healthy, continuously working workers.
    connected = live.get("status") == "ok" and pulse.get("api_server_alive") is True
    return {
        "observed_at": runtime_gateway._observed_at(),
        "source": "original_runtime_http",
        "runtime_original_conectado": connected,
        "runtime_http_health": "ok" if live.get("status") == "ok" else "degraded",
        "observations": observations,
        "full_runtime_verified": False,
        "writes_enabled": False,
    }


def _learning_summary() -> dict[str, Any]:
    journal = runtime_gateway._upstream(
        "GET", "/api/runtime/learning-journal", params={"limit": 20}
    )
    return {
        "observed_at": runtime_gateway._observed_at(),
        "source": "original_runtime_learning_journal",
        "stats": _summary_metrics(journal),
        "full_learning_certified": False,
        "writes_enabled": False,
    }


def attach_private_runtime_routes(app: Any) -> Any:
    """Mount only read-only endpoints; no route can execute a runtime cycle."""

    async def config(request: Request) -> JSONResponse:
        try:
            _authorized(request)
        except HTTPException as exc:
            return _reject(exc.status_code, str(exc.detail))
        return JSONResponse(
            {
                "authenticated": True,
                "runtime_upstream_configured": _upstream_ready(),
                "runtime_upstream_key_present": bool(
                    os.getenv("TRIADE_ACTIONS_UPSTREAM_KEY", "").strip()
                ),
                "private_read_only": True,
                "full_runtime_verified": False,
            },
            headers=_HEADERS,
        )

    async def status(request: Request) -> JSONResponse:
        try:
            _authorized(request)
            if not _upstream_ready():
                return _reject(503, "runtime_endpoint_not_configured")
            return JSONResponse(_runtime_status(), headers=_HEADERS)
        except HTTPException as exc:
            # Never pass through untrusted upstream error descriptions.
            if exc.status_code in (401, 503):
                return _reject(exc.status_code, str(exc.detail))
            return _reject(502, "original_runtime_connection_unavailable")
        except (TypeError, ValueError):
            return _reject(502, "invalid_original_runtime_response")

    async def learning(request: Request) -> JSONResponse:
        try:
            _authorized(request)
            if not _upstream_ready():
                return _reject(503, "runtime_endpoint_not_configured")
            return JSONResponse(_learning_summary(), headers=_HEADERS)
        except HTTPException as exc:
            if exc.status_code in (401, 503):
                return _reject(exc.status_code, str(exc.detail))
            return _reject(502, "original_runtime_connection_unavailable")
        except (TypeError, ValueError):
            return _reject(502, "invalid_original_runtime_response")

    app.routes.extend(
        [
            Route("/api/private/connection", config, methods=["GET"]),
            Route("/api/private/status", status, methods=["GET"]),
            Route("/api/private/learning", learning, methods=["GET"]),
        ]
    )
    return app
