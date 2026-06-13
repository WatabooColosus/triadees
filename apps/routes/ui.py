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

from apps.ui_html import CLEAN_UI_HTML, TRIADE_REACT_UI_HTML

router = APIRouter()
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


DEPRECATED_WRAPPER_HTML = """\
<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"><title>Tríade Ω · Deprecado</title>
<style>
body{{font-family:sans-serif;max-width:600px;margin:4em auto;padding:0 1em;
line-height:1.6;color:#ccc;background:#111;}}
a{{color:#60a5fa;}}
.old{{background:#1e1e1e;border:1px solid #333;padding:1em 1.5em;border-radius:8px;}}
</style></head>
<body>
<h2>⚠️ Vista migrada</h2>
<p>Esta pantalla fue migrada a la SPA React.</p>
<div class="old">
<p>Use <a href="{target}">{target}</a> en la interfaz moderna.</p>
<p><small>Esta ruta legacy se mantiene por compatibilidad y será eliminada en v2.4.</small></p>
</div>
</body></html>"""


def legacy_ui_redirect(target: str = "/") -> RedirectResponse:
    """Redirige una ruta UI legacy a la SPA React."""
    return RedirectResponse(url=target, status_code=302)


def _deprecated_wrapper(target: str = "/") -> HTMLResponse:
    """Wrapper HTML mínimo para rutas legacy."""
    return HTMLResponse(DEPRECATED_WRAPPER_HTML.format(target=target))


def _serve_spa(path: str = "index.html") -> FileResponse:
    file = FRONTEND_DIST / path
    if file.exists() and file.is_file():
        return FileResponse(str(file))
    return FileResponse(str(FRONTEND_DIST / "index.html"))


@router.get("/assets/{path:path}")
def spa_assets(path: str) -> FileResponse:
    return _serve_spa(f"assets/{path}")


# DEPRECATED_UI: migrated to React SPA. Keep until v2.4.
@router.get("/api/ui/clean", response_class=HTMLResponse, include_in_schema=False)
def clean_ui() -> HTMLResponse:
    """DEPRECATED: Vista limpia legacy. Migrada a SPA React."""
    return _deprecated_wrapper("/observabilidad")


@router.get("/api/ui/manifest")
def ui_manifest() -> dict[str, Any]:
    """Contrato dinámico de la interfaz 8010."""
    LIFE_PULSE.record_action("ui_manifest")
    return build_ui_manifest()


# DEPRECATED_UI: migrated to React SPA. Keep until v2.4.
@router.get("/api/ui/legacy", response_class=HTMLResponse, include_in_schema=False)
def legacy_ui() -> HTMLResponse:
    """DEPRECATED: Interfaz React legacy. Migrada a SPA React."""
    return _deprecated_wrapper("/")


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
