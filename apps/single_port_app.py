"""Tríade Ω Single Port App — Entrypoint delgado.

Puerto único 8010 para UI, health, router, compatibilidad,
memoria semántica y runs locales.

La lógica de negocio vive en apps/services.py.
Las rutas viven en apps/routes/{api,health,ui}.py.
El HTML vive en apps/ui_html.py.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from apps.routes.api import router as api_router
from apps.routes.auth import router as auth_router
from apps.routes.governance import router as governance_router
from apps.routes.health import router as health_router
from apps.routes.ui import router as ui_router
from triade.core.life_pulse import LIFE_PULSE
from triade.federation.node_live_registry import NODE_LIVE_REGISTRY

_ALWAYS_ON_RESULT: dict[str, Any] = {}
_ALWAYS_ON_LOCK = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from triade.core.identity_continuity import IdentityContinuity
    from triade.core.runtime_scope import is_test_runtime

    identity = IdentityContinuity(
        os.getenv("TRIADE_DB_PATH", "triade/memory/triade.db")
    ).verify(run_id="single-port-startup")
    app.state.identity_verification = identity
    if identity["integrity"] != "verified":
        global _ALWAYS_ON_RESULT
        with _ALWAYS_ON_LOCK:
            _ALWAYS_ON_RESULT = {
                "status": "degraded_safe_identity_mismatch",
                "background_started": False,
                "identity": identity,
            }
        yield
        return

    if is_test_runtime() or os.getenv("TRIADE_DISABLE_BACKGROUND") == "1":
        with _ALWAYS_ON_LOCK:
            _ALWAYS_ON_RESULT = {
                "status": "isolated_test_runtime",
                "background_started": False,
            }
        yield
        return
    NODE_LIVE_REGISTRY.start()

    # Clean up expired coordination locks from prior runs.
    try:
        from triade.core.orchestrator_coord import OrchestratorCoordinator

        coord = OrchestratorCoordinator()
        cleaned = coord.cleanup()
        if cleaned:
            logging.getLogger("single_port_app").info(
                "Cleaned %d expired orchestrator locks", cleaned
            )
    except (ImportError, OSError, RuntimeError, ValueError, sqlite3.Error):
        logging.getLogger("single_port_app").exception(
            "Failed to clean expired orchestrator locks"
        )

    try:
        from triade.core.always_on import (
            load_always_on_config,
            start_always_on_if_enabled,
        )
        from triade.core.foundational_neurons import ensure_foundational_neurons
        from triade.core.internal_runtime import record_internal_runtime_event
        from triade.core.model_acquisition import start_model_acquisition_background
        from triade.core.worker_autostart import start_workers_if_configured

        foundational_result = ensure_foundational_neurons()
        model_acquisition_result = start_model_acquisition_background()
        cfg = load_always_on_config()
        continuous_result = LIFE_PULSE.configure_continuous_runner(
            enabled=bool(cfg.get("continuous_runner_enabled", False)),
            autonomy_level=str(
                cfg.get("continuous_runner_autonomy_level", "observe_only")
            ),
            interval_seconds=int(cfg.get("continuous_runner_interval_seconds", 60)),
            max_cycles=int(cfg.get("continuous_runner_max_cycles", 0)),
        )
        LIFE_PULSE.start()
        record_internal_runtime_event(
            "always_on_startup_checked",
            "single_port_app",
            {"enabled": cfg.get("enabled")},
        )
        result = start_always_on_if_enabled()
        workers_result = start_workers_if_configured(cfg)
        record_internal_runtime_event(
            "workers_autostart_checked", "single_port_app", workers_result
        )
        metabolism_result = None
        try:
            from triade.metabolism.coordinator import get_coordinator

            mc = get_coordinator()
            mc.load_config()
            metabolism_result = mc.start()
        except (ImportError, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            metabolism_result = {"status": "error", "detail": str(exc)}

        with _ALWAYS_ON_LOCK:
            _ALWAYS_ON_RESULT = {
                **result,
                "workers_always_on": workers_result,
                "neuron_lifecycle_background": continuous_result,
                "foundational_neurons": foundational_result,
                "model_acquisition": model_acquisition_result,
                "metabolism": metabolism_result,
            }
    except (
        OSError,
        ImportError,
        RuntimeError,
        ValueError,
        sqlite3.Error,
    ) as exc:
        with _ALWAYS_ON_LOCK:
            _ALWAYS_ON_RESULT = {
                "status": "error",
                "message": f"always_on_start_failed: {exc}",
            }

    try:
        yield
    finally:
        NODE_LIVE_REGISTRY.stop()
        LIFE_PULSE.stop()


app = FastAPI(title="Tríade Ω Single Port", version="0.9.0", lifespan=lifespan)
app.include_router(governance_router)
app.include_router(auth_router)


@app.middleware("http")
async def public_guarded_mode(request: Request, call_next):
    """Exige sesión real en modo público; una API key global no basta."""
    guarded = os.getenv("TRIADE_PUBLIC_GUARDED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    public_paths = {"/api/auth/login", "/health", "/healthz", "/api/health"}
    if guarded and request.method != "OPTIONS" and request.url.path not in public_paths:
        from triade.security.distributed_auth import DistributedAuthUnavailable
        from triade.security.public_auth import PublicAuthStore

        value = request.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            return JSONResponse(
                status_code=403,
                content={
                    "status": "blocked",
                    "detail": "authenticated_session_required",
                    "public_guarded": True,
                },
            )
        required = "operator" if request.method not in {"GET", "HEAD"} else "viewer"
        try:
            auth = PublicAuthStore(
                os.getenv("TRIADE_AUTH_DB_PATH", "triade/memory/triade.db"),
                rate_limit_per_minute=int(
                    os.getenv("TRIADE_RATE_LIMIT_PER_MINUTE", "60")
                ),
            )
            request.state.principal = auth.authorize(value[7:], required_role=required)
        except DistributedAuthUnavailable:
            return JSONResponse(
                status_code=503, content={"detail": "distributed_auth_unavailable"}
            )
        except RuntimeError:
            return JSONResponse(
                status_code=429, content={"detail": "rate_limit_exceeded"}
            )
        except PermissionError as exc:
            code = 403 if str(exc) == "insufficient_role" else 401
            return JSONResponse(status_code=code, content={"detail": str(exc)})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


app.include_router(health_router)
app.include_router(api_router)
app.include_router(ui_router)


def get_always_on_startup_result() -> dict[str, Any]:
    with _ALWAYS_ON_LOCK:
        return dict(_ALWAYS_ON_RESULT)


# ── Re-exportaciones para compatibilidad con tests ──────────────────────
# Los tests existentes importan símbolos desde apps.single_port_app.
# Mantenemos estas re-exportaciones para que sigan funcionando.

from apps.services import (  # noqa: F401 — re-export
    LOCAL_JOBS,
    android_llm_host_nodes,
    build_model_capacity,
    build_system_pulse,
    clean_model,
    create_local_job,
    docker_status,
    federated_model_plan,
    federation_resource_lease,
    load_local_node_tokens,
    local_federated_nodes,
    local_node_capabilities,
    merge_local_preprocess_results,
    node_model_readiness,
    operational_awareness_context,
    relay_settings,
    router_payload,
    run_context_with_living_awareness,
    save_local_node_tokens,
    split_text_for_nodes,
    system_payload,
    tool_status,
    upsert_local_android_node,
    wait_local_job,
)
