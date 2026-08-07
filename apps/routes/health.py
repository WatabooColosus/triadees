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


def _runtime_path(env_name: str, directory: str) -> str:
    """Resolve storage inside the active checkout unless explicitly configured.

    Cloud containers use ``/app`` as their working directory, so this preserves
    the existing cloud paths while allowing Studio and other local checkouts to
    report readiness against directories they can actually create.
    """
    return os.getenv(env_name, str(Path.cwd() / directory))


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
        "memory": _writable_path(_runtime_path("TRIADE_MEMORY_DIR", "memory")),
        "runs": _writable_path(_runtime_path("TRIADE_RUNS_DIR", "runs")),
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
    except (
        OSError,
        ImportError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
    ) as exc:  # health nunca debe derribar el proceso
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
    content["runtime_mode"] = _runtime_mode()

    return JSONResponse(status_code=200 if healthy else 503, content=content)


def _runtime_mode() -> dict[str, Any]:
    """Qué arrancó realmente el lifespan, no qué dice la configuración.

    `conversation_only` corta el arranque de workers, runner continuo y
    metabolismo. Hasta ahora eso no se veía desde fuera: la app respondía 200 en
    `/health/live` y el chat funcionaba, así que un runtime reducido pasaba por
    uno completo. La certificación necesita distinguirlos sin entrar al proceso.

    Import tardío: `single_port_app` importa este módulo, así que a nivel de
    módulo sería circular; en tiempo de petición ya está cargado.
    """
    try:
        from apps.single_port_app import get_always_on_startup_result

        startup = get_always_on_startup_result()
    except (ImportError, RuntimeError):
        return {"status": "unknown", "conversation_only": None}
    return {
        "status": startup.get("status"),
        "conversation_only": bool(startup.get("conversation_only", False)),
        "background_started": startup.get("background_started"),
    }
