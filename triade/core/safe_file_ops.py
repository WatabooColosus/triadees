"""Safe File Ops · operaciones seguras de archivos con dry-run, verificación y papelera."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from triade.core.autonomy_budget import build_autonomy_budget
from triade.core.integrity_verifier import build_integrity_snapshot, verify_integrity_change
from triade.core.quarantine_trash import trash_path
from triade.core.system_zones import classify_path

EVENT_SOURCE = "safe_file_ops"

SUSPICIOUS_EXTENSIONS = {".exe", ".bat", ".sh", ".dll", ".so", ".dylib", ".bin", ".elf"}


def _norm(info: dict) -> str:
    return info.get("normalized_path", info.get("path", ""))


def _plan(action_type: str, path: str, budget: dict, zones: list[str] | None = None) -> dict[str, Any]:
    return {
        "action_type": action_type,
        "target_paths": [path],
        "zones": zones or [],
        "max_bytes_per_cycle": budget.get("max_bytes_per_cycle", 0),
        "max_files_per_cycle": budget.get("max_files_per_cycle", 0),
    }


def _blocked(info: dict, budget: dict, action: str, budget_level: str) -> dict | None:
    zone = info["zone"]
    if zone == "forbidden":
        return {"status": "blocked_forbidden_zone", "reason": f"Zona prohibida: {info['path']}"}
    if zone == "red":
        return {"status": "requires_human_approval", "reason": "Zona roja requiere aprobación humana."}
    if zone == "yellow_unknown":
        return {"status": "requires_human_approval", "reason": "Zona desconocida requiere aprobación humana o dry-run."}
    if action not in budget.get("allowed_actions", []):
        return {"status": "blocked_budget", "reason": f"Nivel {budget_level} no permite {action} en zona {zone}."}
    return None


def safe_create_file(
    path: str, content: str, budget_level: str, dry_run: bool = True,
) -> dict[str, Any]:
    """Crea archivo de forma segura con dry-run."""
    budget = build_autonomy_budget(budget_level)
    info = classify_path(path)
    target = Path(_norm(info))

    blocked = _blocked(info, budget, "create", budget_level)
    if blocked:
        return blocked

    max_bytes = budget.get("max_bytes_per_cycle", 0)
    if max_bytes > 0 and len(content) > max_bytes:
        return {"status": "blocked_budget", "reason": f"Contenido ({len(content)} bytes) supera máximo del ciclo ({max_bytes} bytes)."}

    ext = Path(target.name).suffix.lower()
    if ext in SUSPICIOUS_EXTENSIONS:
        return {"status": "blocked_budget", "reason": f"Extensión sospechosa no permitida: {ext}"}

    if target.exists():
        return {"status": "error", "reason": f"Ya existe: {path}"}

    plan = _plan("create", str(target), budget, zones=[info["zone"]])
    before = build_integrity_snapshot([str(target)]) if not dry_run else {}

    if dry_run:
        return {
            "status": "dry_run",
            "action": "create",
            "path": str(target),
            "zone": info["zone"],
            "content_length": len(content),
            "max_bytes_per_cycle": max_bytes,
            "plan": plan,
            "budget": budget,
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    after = build_integrity_snapshot([str(target)])
    result = verify_integrity_change(before, after, plan)

    if result.get("status") == "failed":
        target.unlink(missing_ok=True)
        return {"status": result["status"], "action": "create", "path": str(target), "zone": info["zone"], "integrity": result, "requires_rollback": True}

    _register_event("safe_file_created", {"path": str(target), "zone": info["zone"], "status": result["status"], "budget_level": budget_level})

    return {"status": result["status"], "action": "create", "path": str(target), "zone": info["zone"], "integrity": result}


def safe_patch_file(
    path: str, patch_or_content: str, budget_level: str, dry_run: bool = True,
) -> dict[str, Any]:
    """Modifica archivo existente de forma segura."""
    budget = build_autonomy_budget(budget_level)
    info = classify_path(path)
    target = Path(_norm(info))

    blocked = _blocked(info, budget, "patch", budget_level)
    if blocked:
        return blocked

    max_bytes = budget.get("max_bytes_per_cycle", 0)
    if max_bytes > 0 and len(patch_or_content) > max_bytes:
        return {"status": "blocked_budget", "reason": f"Contenido ({len(patch_or_content)} bytes) supera máximo del ciclo ({max_bytes} bytes)."}

    if not target.exists():
        return {"status": "error", "reason": f"No existe: {path}"}

    before = build_integrity_snapshot([str(target)])
    plan = _plan("patch", str(target), budget, zones=[info["zone"]])

    if dry_run:
        return {
            "status": "dry_run",
            "action": "patch",
            "path": str(target),
            "zone": info["zone"],
            "original_size": target.stat().st_size,
            "new_size": len(patch_or_content),
            "budget": budget,
        }

    original = target.read_text(encoding="utf-8")
    target.write_text(patch_or_content, encoding="utf-8")
    after = build_integrity_snapshot([str(target)])
    result = verify_integrity_change(before, after, plan)

    if result.get("status") == "failed":
        target.write_text(original, encoding="utf-8")
        return {"status": result["status"], "action": "patch", "path": str(target), "zone": info["zone"], "integrity": result, "requires_rollback": True}

    _register_event("safe_file_patched", {"path": str(target), "zone": info["zone"], "status": result["status"], "budget_level": budget_level})

    return {"status": result["status"], "action": "patch", "path": str(target), "zone": info["zone"], "integrity": result}


def safe_move_file(
    src: str, dst: str, budget_level: str, dry_run: bool = True,
) -> dict[str, Any]:
    """Mueve archivo de forma segura."""
    budget = build_autonomy_budget(budget_level)
    src_info = classify_path(src)
    dst_info = classify_path(dst)
    src_p = Path(_norm(src_info))
    dst_p = Path(_norm(dst_info))

    if src_info["zone"] == "forbidden" or dst_info["zone"] == "forbidden":
        return {"status": "blocked_forbidden_zone", "reason": "Zona prohibida."}
    if src_info["zone"] == "red" or dst_info["zone"] == "red":
        return {"status": "requires_human_approval", "reason": "Zona roja requiere aprobación humana."}
    if src_info["zone"] == "yellow_unknown" or dst_info["zone"] == "yellow_unknown":
        return {"status": "requires_human_approval", "reason": "Zona desconocida requiere aprobación humana."}
    if "move" not in budget.get("allowed_actions", []):
        return {"status": "blocked_budget", "reason": f"Nivel {budget_level} no permite mover."}
    if not src_p.exists():
        return {"status": "error", "reason": f"No existe: {src}"}
    if dst_p.exists():
        return {"status": "error", "reason": f"Destino ya existe: {dst}"}

    before = build_integrity_snapshot([str(src_p), str(dst_p)])
    plan = _plan("move", str(src_p), budget, zones=[src_info["zone"], dst_info["zone"]])
    plan["target_paths"] = [str(src_p), str(dst_p)]

    if dry_run:
        return {
            "status": "dry_run",
            "action": "move",
            "src": str(src_p),
            "dst": str(dst_p),
            "src_zone": src_info["zone"],
            "dst_zone": dst_info["zone"],
            "budget": budget,
        }

    dst_p.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src_p), str(dst_p))
    after = build_integrity_snapshot([str(src_p), str(dst_p)])
    result = verify_integrity_change(before, after, plan)

    if result.get("status") == "failed":
        shutil.move(str(dst_p), str(src_p))
        return {"status": result["status"], "action": "move", "src": str(src_p), "dst": str(dst_p), "integrity": result, "requires_rollback": True}

    _register_event("safe_file_moved", {"src": str(src_p), "dst": str(dst_p), "src_zone": src_info["zone"], "dst_zone": dst_info["zone"], "status": result["status"], "budget_level": budget_level})

    return {"status": result["status"], "action": "move", "src": str(src_p), "dst": str(dst_p), "src_zone": src_info["zone"], "dst_zone": dst_info["zone"], "integrity": result}


def safe_delete_file(
    path: str, budget_level: str, dry_run: bool = True, reason: str = "Sin motivo especificado",
) -> dict[str, Any]:
    """Borra (mueve a papelera) archivo de forma segura. Nunca unlink directo."""
    budget = build_autonomy_budget(budget_level)
    info = classify_path(path)
    target = Path(_norm(info))

    if info["zone"] == "forbidden":
        return {"status": "blocked_forbidden_zone", "reason": "Zona prohibida."}
    if info["zone"] == "red":
        return {"status": "requires_human_approval", "reason": "Zona roja requiere aprobación humana."}
    if info["zone"] == "yellow_unknown":
        return {"status": "requires_human_approval", "reason": "Zona desconocida requiere aprobación humana."}
    if "delete_to_trash" not in budget.get("allowed_actions", []):
        return {"status": "blocked_budget", "reason": f"Nivel {budget_level} no permite borrar."}
    if not target.exists():
        return {"status": "error", "reason": f"No existe: {path}"}

    if dry_run:
        return {"status": "dry_run", "action": "delete_to_trash", "path": str(target), "zone": info["zone"], "budget": budget}

    result = trash_path(str(target), reason=reason)
    return result


def _register_event(event_type: str, data: dict) -> None:
    try:
        from triade.core.run_system_events import register_system_event
        register_system_event(event_type, {**data, "source": EVENT_SOURCE})
    except ImportError:
        pass
