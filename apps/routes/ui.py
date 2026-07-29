"""Tríade Ω — Route handlers de la interfaz de usuario.

Rutas /, /ui, /api/ui/*.

La UI oficial es React SPA (frontend/dist/).
Las rutas HTML legacy redirigen o muestran aviso de deprecación.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from triade.core.life_pulse import LIFE_PULSE
from triade.core.ui_manifest import build_ui_manifest

router = APIRouter()
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


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
