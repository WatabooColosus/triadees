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


def build_deep_runtime_health() -> dict[str, Any]:
    """Estado operativo profundo acotado, sin inferencia ni escaneos pesados."""
    from triade.core.always_on import build_always_on_status
    from triade.core.ollama_blood import check_ollama_blood
    from triade.core.worker_autostart import build_workers_always_on_status
    from triade.runtime.live_heartbeat import LiveHeartbeat

    db_path = os.getenv("TRIADE_DB_PATH", "triade/memory/triade.db")
    pulse = LiveHeartbeat(db_path).snapshot()
    always_on = build_always_on_status()
    workers = build_workers_always_on_status(db_path=db_path)
    blood = check_ollama_blood()
    checks = {
        "live_heartbeat": pulse.get("status") == "healthy",
        "always_on": bool(
            not always_on.get("enabled")
            or (
                always_on.get("status") == "running"
                and always_on.get("background_thread_alive")
            )
        ),
        "workers": bool(
            not workers.get("configured")
            or (workers.get("active") and workers.get("thread_alive"))
        ),
        "ollama_blood": bool(blood.get("can_reason")),
    }
    return {
        "status": "ok" if all(checks.values()) else "degraded",
        "checks": checks,
        "live_heartbeat": pulse,
        "always_on": {
            "configured_mode": always_on.get("configured_mode"),
            "effective_mode": always_on.get("effective_mode"),
            "status": always_on.get("status"),
            "background_thread_alive": always_on.get("background_thread_alive"),
            "degraded": always_on.get("degraded"),
        },
        "workers": {
            "status": workers.get("status"),
            "active": workers.get("active"),
            "thread_alive": workers.get("thread_alive"),
            "mode_effective": workers.get("mode_effective"),
        },
        "ollama_blood": {
            "status": blood.get("status"),
            "can_reason": blood.get("can_reason"),
            "fallback_mode": blood.get("fallback_mode"),
        },
    }


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
        heartbeat = build_deep_runtime_health()
        heartbeat_ok = heartbeat.get("status") == "ok"
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
    content["supervision"] = _supervision()

    return JSONResponse(status_code=200 if healthy else 503, content=content)


def _supervision() -> dict[str, Any]:
    """Quién mantiene vivo el proceso, y si volvería solo tras un reinicio.

    Va aparte de `status` a propósito: un runtime perfectamente sano puede estar
    sin supervisar, y ese es exactamente el caso que no se veía. Que este bloque
    no influya en el 200/503 es deliberado — la salud del organismo y la de su
    arranque son dos preguntas distintas, y mezclarlas ya escondió una vez la
    segunda detrás de la primera.
    """
    try:
        from triade.runtime.service_supervision import build_service_supervision

        return build_service_supervision(
            port=int(os.getenv("TRIADE_STUDIO_PORT", "8010"))
        )
    except (OSError, ImportError, RuntimeError, ValueError) as exc:
        return {"error": type(exc).__name__, "always_on": None}


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
    # El resultado del arranque guarda el desenlace de cada subsistema, y hasta
    # ahora sólo se publicaban tres campos. El del metabolismo importa
    # especialmente: el lifespan envuelve `get_coordinator()` → `load_config()`
    # → `start()` en un `try` que captura `sqlite3.Error` entre otras. Si algo
    # ahí lanza, el coordinador se queda con los defaults del constructor
    # —`enabled: False`, `mode: observe_only`— y el error queda escrito en un
    # sitio que no expone ninguna superficie: el sistema reporta
    # `status: started` mientras el metabolismo no arrancó nunca.
    #
    # Visto el 2026-08-08 persiguiendo una regresión que costó seis intentos y
    # cuatro diagnósticos equivocados, precisamente por no poder leer esto.
    metabolismo = startup.get("metabolism")
    return {
        "status": startup.get("status"),
        "conversation_only": bool(startup.get("conversation_only", False)),
        "background_started": startup.get("background_started"),
        "metabolism_startup": metabolismo,
        "workers_startup": startup.get("workers_always_on"),
    }
