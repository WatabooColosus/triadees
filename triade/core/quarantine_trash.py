"""Quarantine Trash · papelera reversible con manifiesto.

Nunca elimina definitivamente. Siempre mueve a .triade_trash/.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.system_zones import classify_path, REPO_ROOT

TRASH_DIR = REPO_ROOT / ".triade_trash"
CHUNK = 65536


def _ensure_trash_dir() -> Path:
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    d = TRASH_DIR / date_str
    d.mkdir(parents=True, exist_ok=True)
    return d


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                h.update(chunk)
    except (OSError, PermissionError):
        return ""
    return h.hexdigest()


def trash_path(
    path: str, reason: str, run_ref: str | None = None,
) -> dict[str, Any]:
    """Mueve un archivo a .triade_trash y crea manifest.

    Args:
        path: Ruta relativa o absoluta dentro del repo.
        reason: Motivo del trashed.
        run_ref: (opcional) uuid del runtime cycle.

    Returns:
        Dict con resultado de la operación.
    """
    dst = Path(path)
    if not dst.exists():
        return {"status": "error", "message": f"La ruta no existe: {path}"}

    info = classify_path(str(dst))
    if info["zone"] == "forbidden":
        return {"status": "blocked_forbidden_zone", "message": "Zona prohibida. No se puede mover a papelera.", "classification": info}
    if info["zone"] == "red" and not info["can_delete_to_trash"]:
        return {"status": "requires_human_approval", "message": "Zona roja. Se requiere aprobación humana.", "classification": info}

    try:
        rel = str(dst.relative_to(REPO_ROOT))
    except ValueError:
        return {"status": "error", "message": "Ruta fuera del repositorio."}

    date_dir = _ensure_trash_dir()
    ts = datetime.now(timezone.utc).strftime("%H%M%S%f")
    dest_dir = date_dir / dst.parent.relative_to(REPO_ROOT)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{ts}_{dst.name}"

    sha = _hash_file(dst)
    size = dst.stat().st_size

    shutil.move(str(dst), str(dest_file))

    manifest = {
        "original_path": rel,
        "original_abs": str(dst.resolve()),
        "trash_path": str(dest_file.relative_to(REPO_ROOT)),
        "trash_abs": str(dest_file.resolve()),
        "sha256": sha,
        "size": size,
        "reason": reason,
        "run_ref": run_ref or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "zone": info["zone"],
        "restore_command_key": "restore_trash_item",
    }
    manifest_path = dest_file.parent / f"{ts}_{dst.name}.manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return {
        "status": "ok",
        "message": f"Archivo movido a papelera: {rel}",
        "original_path": rel,
        "trash_path": manifest["trash_path"],
        "manifest_path": str(manifest_path.relative_to(REPO_ROOT)),
        "manifest": manifest,
    }


def restore_trash_item(manifest_path: str) -> dict[str, Any]:
    """Restaura un archivo desde la papelera usando su manifest."""
    mp = REPO_ROOT / manifest_path
    if not mp.exists():
        return {"status": "error", "message": f"Manifest no encontrado: {manifest_path}"}

    with open(mp) as f:
        manifest = json.load(f)

    orig = REPO_ROOT / manifest["original_path"]
    trash_abs = manifest.get("trash_abs", "")
    if not trash_abs or not Path(trash_abs).exists():
        return {"status": "error", "message": "Archivo en papelera no encontrado."}

    orig.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(trash_abs, str(orig))

    mp.unlink()

    return {
        "status": "ok",
        "message": f"Archivo restaurado: {manifest['original_path']}",
        "original_path": manifest["original_path"],
        "manifest": manifest,
    }


def list_trash(limit: int = 100) -> dict[str, Any]:
    """Lista items en la papelera."""
    if not TRASH_DIR.exists():
        return {"items": [], "total_count": 0}

    items = []
    for manifest_file in sorted(TRASH_DIR.rglob("*.manifest.json"), reverse=True):
        if len(items) >= limit:
            break
        try:
            with open(manifest_file) as f:
                data = json.load(f)
            data["manifest_path"] = str(manifest_file.relative_to(REPO_ROOT))
            items.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    return {
        "items": items,
        "total_count": len(items),
        "trash_dir": str(TRASH_DIR.relative_to(REPO_ROOT)),
    }
