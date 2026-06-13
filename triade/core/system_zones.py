"""System Zones · clasificación segura de rutas del proyecto."""

from __future__ import annotations

from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

GREEN_PREFIXES = ["runs/", "artifacts/", "reports/", "logs/", "tmp/", "cache/", ".triade_trash/"]
YELLOW_PREFIXES = ["docs/", "tests/", "frontend/src/", "apps/routes/", "triade/core/", "triade/workers/", "triade/models/"]
RED_PREFIXES = ["triade/memory/", "config/", "migrations/", "pyproject.toml", "package.json", "package-lock.json"]
FORBIDDEN_PATHS = [".git/", ".env", "secrets", "identity_core", "private_keys"]

ZONE_ORDER = ["green", "yellow", "red", "forbidden"]


def classify_path(path: str) -> dict[str, Any]:
    """Clasifica una ruta en zona green/yellow/red/forbidden.

    Returns dict con path, normalized_path, zone, reason y permisos.
    """
    norm = Path(path).resolve()
    repo_str = str(REPO_ROOT.resolve())

    # Path traversal / absoluto fuera del repo
    try:
        norm.relative_to(REPO_ROOT)
    except ValueError:
        return {
            "path": path,
            "normalized_path": str(norm),
            "zone": "forbidden",
            "reason": "Ruta fuera del repositorio.",
            "can_read": False, "can_create": False, "can_modify": False,
            "can_move": False, "can_delete_to_trash": False,
            "requires_human_approval": False,
        }

    rel = str(norm.relative_to(REPO_ROOT))

    # Forbidden
    for fb in FORBIDDEN_PATHS:
        if fb in rel or rel.startswith(fb):
            return {
                "path": path, "normalized_path": str(norm), "zone": "forbidden",
                "reason": f"Ruta prohibida: {fb}.",
                "can_read": False, "can_create": False, "can_modify": False,
                "can_move": False, "can_delete_to_trash": False,
                "requires_human_approval": False,
            }

    # Identity core check
    if "identity_core" in rel.lower():
        return {
            "path": path, "normalized_path": str(norm), "zone": "forbidden",
            "reason": "Zona identity_core prohibida.",
            "can_read": False, "can_create": False, "can_modify": False,
            "can_move": False, "can_delete_to_trash": False,
            "requires_human_approval": False,
        }

    # Red
    for red in RED_PREFIXES:
        if rel == red or rel.startswith(red):
            return {
                "path": path, "normalized_path": str(norm), "zone": "red",
                "reason": f"Zona roja: {red}. Solo lectura sin aprobación humana.",
                "can_read": True, "can_create": False, "can_modify": False,
                "can_move": False, "can_delete_to_trash": False,
                "requires_human_approval": True,
            }

    # Yellow
    for yl in YELLOW_PREFIXES:
        if rel == yl or rel.startswith(yl):
            return {
                "path": path, "normalized_path": str(norm), "zone": "yellow",
                "reason": f"Zona amarilla: {yl}. Requiere dry-run y verificación.",
                "can_read": True, "can_create": True, "can_modify": True,
                "can_move": True, "can_delete_to_trash": True,
                "requires_human_approval": False,
            }

    # Green (default si está dentro del repo)
    return {
        "path": path, "normalized_path": str(norm), "zone": "green",
        "reason": "Zona verde. Operaciones permitidas dentro del presupuesto.",
        "can_read": True, "can_create": True, "can_modify": True,
        "can_move": True, "can_delete_to_trash": True,
        "requires_human_approval": False,
    }
