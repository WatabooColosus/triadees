"""Tríade Ω — Route handlers de la interfaz de usuario.

Rutas /, /ui, /api/ui/*.

La UI oficial es React SPA (frontend/dist/).
Las rutas HTML legacy redirigen o muestran aviso de deprecación.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
)

from apps.internal_graphs_live import (
    GRAPH_BUILDERS,
    REFRESHER,
    build_graph,
    build_live_snapshot,
    event_stream,
    node_detail,
    refresh_artifacts,
)
from apps.internal_graphs_live import _db_path as _graphs_db_path
from triade.core.life_pulse import LIFE_PULSE
from triade.core.ui_manifest import build_ui_manifest

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
INTERNAL_GRAPHS_UI = ROOT / "apps" / "internal_graphs_ui.html"


def legacy_ui_redirect(target: str = "/") -> RedirectResponse:
    """Redirige una ruta UI legacy a la SPA React."""
    return RedirectResponse(url=target, status_code=302)


def _serve_spa(path: str = "index.html") -> FileResponse:
    file = FRONTEND_DIST / path
    if file.exists() and file.is_file():
        return FileResponse(str(file))
    return FileResponse(str(FRONTEND_DIST / "index.html"))


@router.get("/assets/{path:path}")
def spa_assets(path: str) -> FileResponse:
    return _serve_spa(f"assets/{path}")


# DEPRECATED_UI: migrated to React SPA. Keep until v2.4.
@router.get("/api/ui/clean", include_in_schema=False)
def clean_ui() -> RedirectResponse:
    return legacy_ui_redirect("/observabilidad")


@router.get("/api/ui/manifest")
def ui_manifest() -> dict[str, Any]:
    """Contrato dinámico de la interfaz 8010."""
    LIFE_PULSE.record_action("ui_manifest")
    return build_ui_manifest()


# DEPRECATED_UI: migrated to React SPA. Keep until v2.4.
@router.get("/api/ui/legacy", include_in_schema=False)
def legacy_ui() -> RedirectResponse:
    return legacy_ui_redirect("/")


@router.get("/internal-graphs", response_class=HTMLResponse)
@router.get("/ui/internal-graphs", response_class=HTMLResponse)
def internal_graphs_ui() -> FileResponse:
    """Explorador de los grafos internos, conectado sólo a evidencia viva."""
    return FileResponse(str(INTERNAL_GRAPHS_UI), media_type="text/html")


@router.get("/api/internal-graphs/catalog")
def internal_graphs_catalog() -> dict[str, Any]:
    """Qué grafos existen, sin construirlos: es lo que pide la UI al abrirse."""
    LIFE_PULSE.record_action("internal_graphs_catalog")
    return {"graphs": list(GRAPH_BUILDERS), "simulated": False}


@router.get("/api/internal-graphs/graph/{name}")
def internal_graph(
    name: str, limit: int | None = Query(default=None, ge=1, le=100000)
) -> dict[str, Any]:
    """Un grafo completo, con el color de cada nodo ya resuelto por su estado."""
    try:
        payload = build_graph(name, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    LIFE_PULSE.record_action("internal_graphs_read")
    return payload


@router.get("/api/internal-graphs/node/{name}")
def internal_graph_node(name: str, node_id: str) -> dict[str, Any]:
    """Interior de un nodo: metadatos y aristas con su evidencia."""
    try:
        return node_detail(name, node_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/internal-graphs/debt")
def internal_graphs_debt() -> dict[str, Any]:
    """Dónde se rompe el sistema, en elementos concretos con su evidencia.

    Es el mismo informe que consume el worker de deuda: una sola medición para
    quien mira desde fuera y para quien decide desde dentro.

    La estructura sale de artefactos, no de un escaneo en caliente, así que la
    respuesta declara siempre su edad y su estado de refresco. Sin eso, la cifra
    se lee como medición de ahora cuando puede ser de hace horas: fue
    exactamente lo que ocurrió el 2026-08-03, cuando el panel siguió contando
    31 módulos huérfanos ya borrados.
    """
    from triade.observability.introspection import (
        build_debt_report,
        summarise_for_humans,
    )

    trigger = refresh_artifacts()
    # El estado se toma *antes* del informe, no después. Si se leyera al final,
    # una reconstrucción que termina en mitad de la petición devolvería
    # `running: false` junto a un informe medido con los ficheros de antes, y la
    # interfaz dejaría de preguntar justo cuando iba a llegar lo nuevo.
    status = REFRESHER.status()
    report = build_debt_report(ROOT, _graphs_db_path(), allow_build=False)
    report["summary"] = summarise_for_humans(report)
    report["refresh"] = {**status, "trigger": trigger}
    LIFE_PULSE.record_action("internal_graphs_debt")
    return report


@router.get("/api/internal-graphs/snapshot")
def internal_graphs_snapshot(
    file_limit: int | None = Query(default=2000, ge=1, le=100000),
) -> dict[str, Any]:
    """Snapshot físico y neural en una sola lectura."""
    return build_live_snapshot(file_limit=file_limit)


@router.get("/api/internal-graphs/health")
def internal_graphs_health() -> dict[str, Any]:
    """Salud y progreso medidos por el contrato canónico del watchdog."""
    from apps.internal_graphs_live import system_health

    return system_health()


@router.get("/api/internal-graphs/search")
def internal_graphs_search(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    from apps.internal_graphs_live import search_system

    return search_system(q, limit=limit)


@router.get("/api/internal-graphs/timeline")
def internal_graphs_timeline(
    limit: int = Query(default=100, ge=1, le=500),
    run_id: str | None = Query(default=None, max_length=200),
    task_id: str | None = Query(default=None, max_length=200),
) -> dict[str, Any]:
    from apps.internal_graphs_live import operational_timeline

    return operational_timeline(limit=limit, run_id=run_id, task_id=task_id)


@router.get("/api/internal-graphs/stream")
def internal_graphs_stream() -> StreamingResponse:
    """Pulso SSE: estados por grafo mientras el runtime trabaja."""
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
@router.get("/observabilidad", response_class=HTMLResponse)
@router.get("/ui/observabilidad", response_class=HTMLResponse)
def ui() -> FileResponse:
    """Entrada pública única: la SPA compilada es un requisito de despliegue."""
    spa_index = FRONTEND_DIST / "index.html"
    if spa_index.exists():
        return FileResponse(str(spa_index))
    return HTMLResponse(
        "<h1>Tríade Ω</h1><p>Frontend no compilado.</p>", status_code=503
    )
