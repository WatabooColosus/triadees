"""Tríade Ω — Route handlers de la interfaz de usuario.

Rutas /, /ui, /api/ui/*.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from triade.core.life_pulse import LIFE_PULSE
from triade.core.ui_manifest import build_ui_manifest

from apps.ui_html import CLEAN_UI_HTML, TRIADE_REACT_UI_HTML

router = APIRouter()


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
def ui() -> str:
    """Entrada principal pública: sirve la consola limpia."""
    return CLEAN_UI_HTML
