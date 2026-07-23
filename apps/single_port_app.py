"""Tríade Ω Single Port App — Entrypoint delgado.

Puerto único 8010 para UI, health, router, compatibilidad,
memoria semántica y runs locales.

La lógica de negocio vive en apps/services.py.
Las rutas viven en apps/routes/{api,ui}.py.
El HTML vive en apps/ui_html.py.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI

from triade.core.life_pulse import LIFE_PULSE
from triade.federation.node_live_registry import NODE_LIVE_REGISTRY

from apps.routes.api import router as api_router
from apps.routes.ui import router as ui_router

_ALWAYS_ON_RESULT: dict[str, Any] = {}
_ALWAYS_ON_LOCK = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    LIFE_PULSE.start()
    NODE_LIVE_REGISTRY.start()

    # Clean up expired coordination locks from prior runs.
    try:
        from triade.core.orchestrator_coord import OrchestratorCoordinator
        coord = OrchestratorCoordinator()
        cleaned = coord.cleanup()
        if cleaned:
            import logging
            logging.getLogger("single_port_app").info("Cleaned %d expired orchestrator locks", cleaned)
    except Exception:
        pass

    global _ALWAYS_ON_RESULT
    try:
        from triade.core.always_on import load_always_on_config, start_always_on_if_enabled
        from triade.core.worker_autostart import start_workers_if_configured
        from triade.core.internal_runtime import record_internal_runtime_event
        cfg = load_always_on_config()
        record_internal_runtime_event("always_on_startup_checked", "single_port_app", {"enabled": cfg.get("enabled")})
        result = start_always_on_if_enabled()
        workers_result = start_workers_if_configured(cfg)
        record_internal_runtime_event("workers_autostart_checked", "single_port_app", workers_result)
        with _ALWAYS_ON_LOCK:
            _ALWAYS_ON_RESULT = {**result, "workers_always_on": workers_result}
    except Exception as exc:
        with _ALWAYS_ON_LOCK:
            _ALWAYS_ON_RESULT = {"status": "error", "message": f"always_on_start_failed: {exc}"}

    try:
        yield
    finally:
        NODE_LIVE_REGISTRY.stop()
        LIFE_PULSE.stop()


app = FastAPI(title="Tríade Ω Single Port", version="0.9.0", lifespan=lifespan)
app.include_router(api_router)
app.include_router(ui_router)


def get_always_on_startup_result() -> dict[str, Any]:
    with _ALWAYS_ON_LOCK:
        return dict(_ALWAYS_ON_RESULT)


# ── Re-exportaciones para compatibilidad con tests ──────────────────────
# Los tests existentes importan símbolos desde apps.single_port_app.
# Mantenemos estas re-exportaciones para que sigan funcionando.

from apps.services import (  # noqa: E402, F401 — re-export
    LOCAL_JOBS,
    federated_model_plan,
    federation_resource_lease,
    local_node_capabilities,
    create_local_job,
    build_model_capacity,
    clean_model,
    system_payload,
    router_payload,
    relay_settings,
    load_local_node_tokens,
    save_local_node_tokens,
    upsert_local_android_node,
    wait_local_job,
    local_federated_nodes,
    android_llm_host_nodes,
    split_text_for_nodes,
    merge_local_preprocess_results,
    tool_status,
    docker_status,
    node_model_readiness,
    build_system_pulse,
    operational_awareness_context,
    run_context_with_living_awareness,
)
