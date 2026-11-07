"""Tríade Ω – minimal, explicitly opt-in ChatGPT Actions HTTP gateway.

This service only proxies a small allowlist to an existing Tríade runtime.
It does not run a second Bodega, overwrite memory, or invoke models on its own.
All Actions endpoints require a distinct gateway Bearer token. The stateful
run action is disabled unless explicitly enabled in the hosting environment.
"""

from __future__ import annotations

import hmac
import os
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

app = FastAPI(
    title="Tríade Ω — ChatGPT Actions Gateway",
    description=(
        "Puente autenticado hacia un runtime Tríade existente. "
        "Consulta el estado y aprendizaje; la ejecución está desactivada por defecto."
    ),
    version="0.1.0",
)
_bearer = HTTPBearer(auto_error=False)
_TIMEOUT_SECONDS = 12.0
_ALLOWED_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class RunInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=3000)
    use_ollama: bool = Field(default=False)


def _required_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected = os.environ.get("TRIADE_ACTIONS_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="gateway_not_configured")
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(credentials.credentials, expected)
    ):
        raise HTTPException(status_code=401, detail="invalid_gateway_token")


def _upstream_url() -> str:
    base = os.environ.get("TRIADE_ACTIONS_UPSTREAM_URL", "").strip().rstrip("/")
    parsed = urlsplit(base)
    # Prevent accidental plaintext credentials over an external network.
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in _ALLOWED_LOCAL_HOSTS)
        )
    ):
        raise HTTPException(status_code=503, detail="upstream_not_safely_configured")
    return base


def _upstream(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = _upstream_url()
    headers = {"Accept": "application/json"}
    upstream_key = os.environ.get("TRIADE_ACTIONS_UPSTREAM_KEY", "").strip()
    if upstream_key:
        headers["X-Triade-Api-Key"] = upstream_key
    try:
        # No redirects, environment proxies, dynamic paths, or caller-supplied URLs.
        with httpx.Client(
            timeout=_TIMEOUT_SECONDS, follow_redirects=False, trust_env=False
        ) as client:
            response = client.request(
                method,
                base + path,
                headers=headers,
                params=params,
                json=payload,
            )
        if response.status_code != 200:
            raise HTTPException(
                status_code=502, detail="runtime_unavailable_or_rejected"
            )
        if len(response.content) > 256_000:
            raise HTTPException(status_code=502, detail="runtime_response_too_large")
        result = response.json()
        if not isinstance(result, dict):
            raise HTTPException(status_code=502, detail="runtime_invalid_response")
        return result
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
        raise HTTPException(
            status_code=502, detail="runtime_connection_failed"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="runtime_invalid_json") from exc


def _observed_at() -> str:
    return datetime.now(UTC).isoformat()


@app.get("/health", include_in_schema=False)
def health() -> dict[str, Any]:
    """Process liveness only; never claims that the Tríade runtime is alive."""
    return {"status": "ok", "service": "triade-chatgpt-gateway"}


@app.get("/actions/status", operation_id="consultar_estado_triade")
def status(_: Annotated[None, Depends(_required_token)]) -> dict[str, Any]:
    """Summarize observed runtime heartbeat, without raw memory or credentials."""
    live = _upstream("GET", "/health/live")
    pulse = _upstream("GET", "/api/runtime/heartbeat")
    keys = (
        "status",
        "api_server_alive",
        "runtime_enabled",
        "background_thread_alive",
        "workers_active",
        "mode",
        "last_cycle_at",
        "heartbeat_cycle",
        "heartbeat_age_ms",
        "can_reason",
        "fallback_mode",
    )
    return {
        "observed_at": _observed_at(),
        "source": "triade_runtime_http",
        "http_health": live.get("status", "unknown"),
        "pulse": {key: pulse[key] for key in keys if key in pulse},
        "full_runtime_verified": bool(
            live.get("status") == "ok"
            and pulse.get("runtime_enabled")
            and pulse.get("workers_active")
        ),
    }


@app.get("/actions/learning", operation_id="consultar_aprendizaje_triade")
def learning(
    _: Annotated[None, Depends(_required_token)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, Any]:
    """Provide a bounded journal summary; no raw lessons or candidate data."""
    journal = _upstream("GET", "/api/runtime/learning-journal", params={"limit": limit})
    summary: dict[str, Any] = {}
    # Only explicit statistical fields: no surprise exposure of user data.
    for key in (
        "status",
        "since_hours",
        "total_runs",
        "total_cycles",
        "total_sessions",
        "total_applications",
        "lessons_prepared",
        "consolidations",
        "summary",
        "counts",
    ):
        value = journal.get(key)
        if isinstance(value, (str, int, float, bool, type(None))):
            summary[key] = value
        elif isinstance(value, dict):
            summary[key] = {
                k: v
                for k, v in value.items()
                if isinstance(k, str)
                and isinstance(v, (str, int, float, bool, type(None)))
            }
    return {
        "observed_at": _observed_at(),
        "source": "triade_runtime_http",
        "journal": summary,
        "full_learning_certified": False,  # Requires independent gates.
    }


@app.post("/actions/run", operation_id="ejecutar_ciclo_triade")
def run(
    body: RunInput,
    _: Annotated[None, Depends(_required_token)],
) -> dict[str, Any]:
    """Run the real Tríade cycle, but only when the operator opts in."""
    if os.environ.get("TRIADE_ACTIONS_ALLOW_RUN", "0").lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise HTTPException(status_code=403, detail="run_disabled_by_operator")
    result = _upstream(
        "POST",
        "/api/run",
        payload={
            "text": body.text,
            "source": "chatgpt-actions",
            "use_ollama": body.use_ollama,
            "semantic_recall_enabled": False,
            "semantic_allow_experimental": False,
            "debug": False,
        },
    )
    # Only expose the answer and linkage IDs; never raw traces or memory diffs.
    return {
        "observed_at": _observed_at(),
        "source": "triade_runtime_http",
        "status": result.get("status", "unknown"),
        "response": str(result.get("response", ""))[:6000],
        "run_id": result.get("run_id"),
        "request_id": result.get("request_id"),
        "error_type": result.get("error_type"),
    }
