"""Tríade Ω — rutas de interfaz y observabilidad viva."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse

from apps.internal_graphs_live import build_live_snapshot, event_stream
from triade.core.life_pulse import LIFE_PULSE
from triade.core.ui_manifest import build_ui_manifest

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
INTERNAL_GRAPHS_UI = ROOT / "apps" / "internal_graphs_ui.html"


def legacy_ui_redirect(target: str = "/") -> RedirectResponse:
    return RedirectResponse(url=target, status_code=302)


def _serve_spa(path: str = "index.html") -> FileResponse:
    file = FRONTEND_DIST / path
    if file.exists() and file.is_file():
        return FileResponse(str(file))
    return FileResponse(str(FRONTEND_DIST / "index.html"))


@router.get("/assets/{path:path}")
def spa_assets(path: str) -> FileResponse:
    return _serve_spa(f"assets/{path}")


@router.get("/api/ui/clean", include_in_schema=False)
def clean_ui() -> RedirectResponse:
    return legacy_ui_redirect("/observabilidad")


@router.get("/api/ui/manifest")
def ui_manifest() -> dict[str, Any]:
    LIFE_PULSE.record_action("ui_manifest")
    return build_ui_manifest()


@router.get("/api/ui/legacy", include_in_schema=False)
def legacy_ui() -> RedirectResponse:
    return legacy_ui_redirect("/")


@router.get("/internal-graphs", response_class=HTMLResponse)
@router.get("/ui/internal-graphs", response_class=HTMLResponse)
def internal_graphs_ui() -> FileResponse:
    """Explorador HTML/CSS/JS conectado únicamente a evidencia viva."""
    return FileResponse(str(INTERNAL_GRAPHS_UI), media_type="text/html")


@router.get("/api/internal-graphs/snapshot")
def internal_graphs_snapshot() -> dict[str, Any]:
    """Snapshot real del filesystem, SQLite y proceso Python actual."""
    return build_live_snapshot()


@router.get("/api/internal-graphs/stream")
def internal_graphs_stream() -> StreamingResponse:
    """Flujo Server-Sent Events actualizado cada dos segundos."""
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
@router.get("/observabilidad", response_class=HTMLResponse)
@router.get("/ui/observabilidad", response_class=HTMLResponse)
def ui() -> FileResponse | HTMLResponse:
    spa_index = FRONTEND_DIST / "index.html"
    if spa_index.exists():
        return FileResponse(str(spa_index))
    return HTMLResponse("<h1>Tríade Ω</h1><p>Frontend no compilado.</p>", status_code=503)
