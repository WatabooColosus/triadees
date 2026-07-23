"""Health endpoints separados para operación cloud.

- /health/live: confirma que el proceso HTTP responde.
- /health/ready: confirma almacenamiento local y dependencias declaradas.
- /health/deep: añade heartbeat interno para diagnóstico operativo.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from triade.core.internal_runtime import build_runtime_heartbeat

router = APIRouter(prefix="/health", tags=["health"])


def _tcp_check(url: str | None, default_port: int) -> dict[str, Any]:
    if not url:
        return {"configured": False, "ok": True, "reason": "not_configured"}

    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or default_port
    if not host:
        return {"configured": True, "ok": False, "reason": "invalid_url"}

    try:
        with socket.create_connection((host, port), timeout=2):
            return {"configured": True, "ok": True, "host": host, "port": port}
    except OSError as exc:
        return {
            "configured": True,
            "ok": False,
            "host": host,
            "port": port,
            "reason": type(exc).__name__,
        }


def _writable_path(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".triade-health-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return {"path": str(path), "ok": True}
    except OSError as exc:
        return {"path": str(path), "ok": False, "reason": type(exc).__name__}


@router.get("/live")
def live() -> dict[str, Any]:
    return {
        "status": "alive",
        "service": "triade-omega",
        "cloud_mode": os.getenv("TRIADE_CLOUD_MODE") == "1",
    }


@router.get("/ready")
def ready() -> JSONResponse:
    checks = {
        "memory": _writable_path(os.getenv("TRIADE_MEMORY_DIR", "/app/memory")),
        "runs": _writable_path(os.getenv("TRIADE_RUNS_DIR", "/app/runs")),
        "postgres": _tcp_check(os.getenv("DATABASE_URL"), 5432),
        "valkey": _tcp_check(os.getenv("REDIS_URL"), 6379),
    }
    ok = all(bool(check.get("ok")) for check in checks.values())
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"status": "ready" if ok else "not_ready", "checks": checks},
    )


@router.get("/deep")
def deep() -> JSONResponse:
    readiness = ready()
    ready_payload = readiness.body.decode("utf-8")

    try:
        heartbeat = build_runtime_heartbeat()
        heartbeat_ok = isinstance(heartbeat, dict)
        heartbeat_error = None
    except Exception as exc:  # health nunca debe derribar el proceso
        heartbeat = {}
        heartbeat_ok = False
        heartbeat_error = type(exc).__name__

    ready_ok = readiness.status_code == 200
    healthy = ready_ok and heartbeat_ok
    content: dict[str, Any] = {
        "status": "healthy" if healthy else "degraded",
        "ready": ready_ok,
        "heartbeat_ok": heartbeat_ok,
        "heartbeat": heartbeat,
    }
    if heartbeat_error:
        content["heartbeat_error"] = heartbeat_error
    content["readiness_raw"] = ready_payload

    return JSONResponse(status_code=200 if healthy else 503, content=content)
