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
from apps.routes.knowledge import router as knowledge_router
from apps.routes.ui import router as ui_router
from triade.core.life_pulse import LIFE_PULSE
from triade.core.request_context import (
    REQUEST_ID_HEADER,
    normalize_request_id,
    reset_request_id,
    set_request_id,
)
from triade.db import sqlite3
from triade.federation.node_live_registry import NODE_LIVE_REGISTRY

_ALWAYS_ON_RESULT: dict[str, Any] = {}
_ALWAYS_ON_LOCK = threading.Lock()


#: Plazo total que el apagado se permite gastar. `TimeoutStopSec` de la unit son
#: 30 s y systemd remata con SIGKILL al vencer: hay que terminar cómodamente
#: antes, o el cierre ordenado no llega a ocurrir y volvemos al remate.
_SHUTDOWN_BUDGET_SECONDS = 12.0


def _stop_background(db_path: str) -> dict[str, Any]:
    """Para lo que el arranque levantó, en orden inverso y con plazo acotado.

    El arranque encendía seis subsistemas —always_on, workers, life_pulse,
    registro federado, metabolismo y watchdog— y el cierre paraba dos. Los
    demás seguían vivos, el proceso no terminaba, y systemd lo remataba con
    SIGKILL a los 30 s dejando la unit en `failed`. La propia unit lo tenía
    escrito como si fuera el diseño: «los hilos de fondo siguen vivos más de
    30 s… systemd remata con SIGKILL».

    Un SIGKILL no es un apagado: las tareas en vuelo se quedan en `running`,
    los leases sin devolver y la base sin punto de control. Eso es exactamente
    el estado en que apareció Tríade tras el apagado del servidor del
    2026-08-11.

    Cada parada va en su propio try: si una revienta, las demás tienen que
    ocurrir igual. Y ninguna puede colgarse —`MetabolismCoordinator.stop()`
    espera 30 s por defecto, que es justo el plazo entero de systemd—, así que
    el plazo se pasa explícito.
    """
    resultados: dict[str, Any] = {}
    errores = (OSError, ImportError, RuntimeError, ValueError, sqlite3.Error)

    # Primero lo que produce trabajo nuevo, para que lo de abajo pueda drenar.
    try:
        from triade.core.worker_autostart import stop_workers_always_on

        resultados["workers"] = stop_workers_always_on(db_path=db_path)
    except errores as exc:
        resultados["workers"] = {"status": "error", "detail": str(exc)}

    try:
        from triade.metabolism.coordinator import get_coordinator

        resultados["metabolism"] = get_coordinator(db_path=db_path).stop(
            timeout=_SHUTDOWN_BUDGET_SECONDS / 2
        )
    except errores as exc:
        resultados["metabolism"] = {"status": "error", "detail": str(exc)}

    try:
        from triade.core.always_on import stop_always_on

        resultados["always_on"] = stop_always_on(db_path=db_path)
    except errores as exc:
        resultados["always_on"] = {"status": "error", "detail": str(exc)}

    for nombre, parar in (
        ("node_live_registry", NODE_LIVE_REGISTRY.stop),
        ("life_pulse", LIFE_PULSE.stop),
    ):
        try:
            parar()
            resultados[nombre] = {"status": "stopped"}
        except errores as exc:
            resultados[nombre] = {"status": "error", "detail": str(exc)}

    return resultados


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from triade.core.identity_continuity import IdentityContinuity
    from triade.core.runtime_scope import is_test_runtime
    from triade.memory.db_pragmas import ensure_durability_pragmas

    # Antes de cualquier otra cosa: garantizar WAL. Es idempotente y persistente,
    # pero si la base se creara desde cero sin esto arrancaría en journal_mode
    # 'delete' y no soportaría la concurrencia real del sistema (P1-04).
    db_path = os.getenv("TRIADE_DB_PATH", "triade/memory/triade.db")
    app.state.durability_pragmas = ensure_durability_pragmas(db_path)

    identity = IdentityContinuity(db_path).verify(run_id="single-port-startup")
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

    # Fase 1: conservar los defaults Always-On para despliegues generales,
    # pero permitir un modo explícito de recuperación conversacional que no
    # arranque workers, runner continuo ni metabolismo antes del chat.
    from triade.core.always_on import load_always_on_config

    conversation_only = bool(load_always_on_config().get("conversation_only", False))
    if conversation_only:
        with _ALWAYS_ON_LOCK:
            _ALWAYS_ON_RESULT = {
                "status": "conversation_only",
                "background_started": False,
                "conversation_only": True,
            }
        try:
            yield
        finally:
            NODE_LIVE_REGISTRY.stop()
            LIFE_PULSE.stop()
        return

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
        from triade.capabilities import bootstrap_core_capabilities
        from triade.core.always_on import (
            load_always_on_config,
            start_always_on_if_enabled,
        )
        from triade.core.foundational_neurons import ensure_foundational_neurons
        from triade.core.internal_runtime import record_internal_runtime_event
        from triade.core.model_acquisition import start_model_acquisition_background
        from triade.core.worker_autostart import start_workers_if_configured

        foundational_result = ensure_foundational_neurons()
        # Mismo lugar y mismo motivo que las neuronas fundacionales: es un
        # arranque idempotente que deja existiendo lo que el sistema da por
        # supuesto. Sólo lo llamaban los tests, así que `capability_registry` y
        # `capability_history` llevaban toda su vida en cero, `CapabilityMatrix`
        # no tenía nada que leer —y por eso figuraba como módulo sin importador—
        # y `CapabilityPolicyGuard` resolvía sobre un registro vacío.
        #
        # No sobrescribe nada: `bootstrap_core_capabilities` consulta cada
        # capacidad y sólo registra las que faltan, con test de idempotencia.
        # Esa distinción importa aquí, donde ya hubo rutinas de arranque que
        # borraron lo aprendido.
        capabilities_result = bootstrap_core_capabilities()
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
        result = start_always_on_if_enabled(db_path=db_path)
        workers_result = start_workers_if_configured(cfg, db_path=db_path)
        record_internal_runtime_event(
            "workers_autostart_checked", "single_port_app", workers_result
        )
        # El watchdog se arranca aquí por la misma razón que los workers: la
        # unidad `deploy/systemd/triade-watchdog.service` describe un despliegue
        # que en el Studio no existe —el runtime corre bajo `nohup uvicorn`—, y
        # por eso llevaba días sin ejecutarse con `runtime_health_snapshots`
        # congelada (F-040).
        from triade.runtime.watchdog_autostart import start_watchdog_if_enabled

        watchdog_result = start_watchdog_if_enabled(cfg, db_path=db_path)
        record_internal_runtime_event(
            "runtime_watchdog_checked", "single_port_app", watchdog_result
        )
        metabolism_result = None
        try:
            from triade.metabolism.coordinator import get_coordinator

            mc = get_coordinator(db_path=db_path)
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
                "core_capabilities": len(capabilities_result),
                "model_acquisition": model_acquisition_result,
                "metabolism": metabolism_result,
                "runtime_watchdog": watchdog_result,
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
        _stop_background(db_path)


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
    # `img-src` se separa de `default-src` sólo por el favicon: va embebido como
    # `data:image/svg+xml` en `frontend/index.html` —se puso así para no pedir
    # un `/favicon.ico` que daba 404 permanente en consola— y `default-src
    # 'self'` lo bloqueaba, cambiando un 404 por una violación de CSP. La SPA
    # cargaba entera igual, pero arrancaba con un error rojo en consola, que es
    # justo el ruido que hace que nadie mire los errores de verdad.
    #
    # Se relaja lo mínimo: `data:` sólo para imágenes. Auditado sobre el bundle
    # publicado, el favicon es el único recurso `data:` de toda la aplicación
    # (los `data:` del JS minificado son literales de objeto, no URIs). Scripts,
    # estilos, conexiones y frames siguen cayendo en `default-src 'self'`.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:"
    )
    return response


# Registrado DESPUÉS de `public_guarded_mode` a propósito: Starlette inserta
# cada middleware en la posición 0 de la pila, así que el último registrado es
# el más EXTERNO y por tanto el primero en ejecutarse. Este tiene que envolver
# al guardián, no al revés — una petición rechazada con 403 por safety o por
# autenticación es justo la que más falta hace poder correlacionar, y si el id
# naciera por dentro esas serían las únicas que saldrían sin él.
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Da identidad a cada petición y se la devuelve al cliente."""
    request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
    token = set_request_id(request_id)
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    finally:
        # Sin el reset, el id sobrevive en el contexto del worker y la siguiente
        # petición que no traiga cabecera heredaría el de la anterior.
        reset_request_id(token)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


app.include_router(health_router)
app.include_router(api_router)
app.include_router(knowledge_router)
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
