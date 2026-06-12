"""Tríade Ω — Route handlers de la interfaz de usuario.

Rutas /, /ui, /api/ui/*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from triade.core.life_pulse import LIFE_PULSE
from triade.core.ui_manifest import build_ui_manifest

from apps.ui_html import CLEAN_UI_HTML, TRIADE_REACT_UI_HTML

router = APIRouter()
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def _serve_spa(path: str = "index.html") -> FileResponse:
    file = FRONTEND_DIST / path
    if file.exists() and file.is_file():
        return FileResponse(str(file))
    return FileResponse(str(FRONTEND_DIST / "index.html"))


@router.get("/assets/{path:path}")
def spa_assets(path: str) -> FileResponse:
    return _serve_spa(f"assets/{path}")


@router.get("/api/ui/clean", response_class=HTMLResponse)
def clean_ui() -> str:
    """Vista limpia experimental de la consola 8010."""
    return CLEAN_UI_HTML


@router.get("/api/ui/manifest")
def ui_manifest() -> dict[str, Any]:
    """Contrato dinámico de la interfaz 8010."""
    LIFE_PULSE.record_action("ui_manifest")
    return build_ui_manifest()


@router.get("/api/ui/legacy", response_class=HTMLResponse)
def legacy_ui() -> str:
    """Interfaz React anterior conservada como respaldo."""
    return TRIADE_REACT_UI_HTML


@router.get("/", response_class=HTMLResponse)
@router.get("/ui", response_class=HTMLResponse)
@router.get("/observabilidad", response_class=HTMLResponse)
@router.get("/ui/observabilidad", response_class=HTMLResponse)
def ui() -> FileResponse:
    """Entrada principal pública: sirve la SPA React si existe, o la consola limpia."""
    spa_index = FRONTEND_DIST / "index.html"
    if spa_index.exists():
        return FileResponse(str(spa_index))
    return HTMLResponse(CLEAN_UI_HTML)
