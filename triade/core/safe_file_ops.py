"""Safe File Ops · operaciones seguras de archivos con dry-run, verificación y papelera."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.autonomy_budget import build_autonomy_budget
from triade.core.integrity_verifier import build_integrity_snapshot, verify_integrity_change
from triade.core.quarantine_trash import trash_path
from triade.core.system_zones import classify_path, REPO_ROOT

EVENT_SOURCE = "safe_file_ops"


def _path_classify(path: str) -> dict[str, Any]:
    return classify_path(path)


def _plan(action_type: str, path: str, budget: dict) -> dict[str, Any]:
    return {
        "action_type": action_type,
        "target_paths": [path],
        "zones": [],
        "max_bytes_per_cycle": budget.get("max_bytes_per_cycle", 0),
        "max_files_per_cycle": budget.get("max_files_per_cycle", 0),
    }


def safe_create_file(
    path: str, content: str, budget_level: str, dry_run: bool = True,
) -> dict[str, Any]:
    """Crea archivo de forma segura con dry-run."""
    target = Path(path)
    budget = build_autonomy_budget(budget_level)
    info = _path_classify(str(target))

    if info["zone"] == "forbidden":
        return {"status": "blocked_forbidden_zone", "reason": f"Zona prohibida: {path}"}
    if info["zone"] == "red":
        return {"status": "requires_human_approval", "reason": "Zona roja requiere aprobación humana."}
    if "create" not in budget.get("allowed_actions", []):
        return {"status": "blocked_budget", "reason": f"Nivel {budget_level} no permite crear en zona {info['zone']}."}

    plan = _plan("create", str(target), budget)
    before = build_integrity_snapshot([str(target)]) if not dry_run else {}
    if target.exists():
        return {"status": "error", "reason": f"Ya existe: {path}"}

    if dry_run:
        return {
            "status": "dry_run",
            "action": "create",
            "path": str(target),
            "zone": info["zone"],
            "content_length": len(content),
            "plan": plan,
            "budget": budget,
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    after = build_integrity_snapshot([str(target)])
    result = verify_integrity_change(before, after, plan)

    _register_event("safe_file_created", {
        "path": str(target), "zone": info["zone"],
        "status": result["status"], "budget_level": budget_level,
    })

    return {
        "status": result["status"],
        "action": "create",
        "path": str(target),
        "zone": info["zone"],
        "integrity": result,
    }


def safe_patch_file(
    path: str, patch_or_content: str, budget_level: str, dry_run: bool = True,
) -> dict[str, Any]:
    """Modifica archivo existente de forma segura."""
    target = Path(path)
    budget = build_autonomy_budget(budget_level)
    info = _path_classify(str(target))

    if info["zone"] == "forbidden":
        return {"status": "blocked_forbidden_zone", "reason": f"Zona prohibida: {path}"}
    if info["zone"] == "red":
        return {"status": "requires_human_approval", "reason": "Zona roja requiere aprobación humana."}
    if "patch" not in budget.get("allowed_actions", []):
        return {"status": "blocked_budget", "reason": f"Nivel {budget_level} no permite modificar."}
    if not target.exists():
        return {"status": "error", "reason": f"No existe: {path}"}

    before = build_integrity_snapshot([str(target)])
    plan = _plan("patch", str(target), budget)

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

    target.write_text(patch_or_content, encoding="utf-8")
    after = build_integrity_snapshot([str(target)])
    result = verify_integrity_change(before, after, plan)

    _register_event("safe_file_patched", {
        "path": str(target), "zone": info["zone"],
        "status": result["status"], "budget_level": budget_level,
    })

    return {
        "status": result["status"],
        "action": "patch",
        "path": str(target),
        "zone": info["zone"],
        "integrity": result,
    }


def safe_move_file(
    src: str, dst: str, budget_level: str, dry_run: bool = True,
) -> dict[str, Any]:
    """Mueve archivo de forma segura."""
    src_p = Path(src)
    dst_p = Path(dst)
    budget = build_autonomy_budget(budget_level)
    src_info = _path_classify(str(src_p))
    dst_info = _path_classify(str(dst_p))

    if src_info["zone"] == "forbidden" or dst_info["zone"] == "forbidden":
        return {"status": "blocked_forbidden_zone", "reason": "Zona prohibida."}
    if src_info["zone"] == "red":
        return {"status": "requires_human_approval", "reason": "Origen zona roja."}
    if "move" not in budget.get("allowed_actions", []):
        return {"status": "blocked_budget", "reason": f"Nivel {budget_level} no permite mover."}
    if not src_p.exists():
        return {"status": "error", "reason": f"No existe: {src}"}

    before = build_integrity_snapshot([str(src_p), str(dst_p)])
    plan = _plan("move", str(src_p), budget)
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

    _register_event("safe_file_moved", {
        "src": str(src_p), "dst": str(dst_p),
        "src_zone": src_info["zone"], "dst_zone": dst_info["zone"],
        "status": result["status"], "budget_level": budget_level,
    })

    return {
        "status": result["status"],
        "action": "move",
        "src": str(src_p),
        "dst": str(dst_p),
        "src_zone": src_info["zone"],
        "dst_zone": dst_info["zone"],
        "integrity": result,
    }


def safe_delete_file(
    path: str, budget_level: str, dry_run: bool = True, reason: str = "Sin motivo especificado",
) -> dict[str, Any]:
    """Borra (mueve a papelera) archivo de forma segura."""
    target = Path(path)
    budget = build_autonomy_budget(budget_level)
    info = _path_classify(str(target))

    if info["zone"] == "forbidden":
        return {"status": "blocked_forbidden_zone", "reason": "Zona prohibida."}
    if info["zone"] == "red":
        return {"status": "requires_human_approval", "reason": "Zona roja requiere aprobación humana."}
    if "delete_to_trash" not in budget.get("allowed_actions", []):
        return {"status": "blocked_budget", "reason": f"Nivel {budget_level} no permite borrar."}
    if not target.exists():
        return {"status": "error", "reason": f"No existe: {path}"}

    if dry_run:
        return {
            "status": "dry_run",
            "action": "delete_to_trash",
            "path": str(target),
            "zone": info["zone"],
            "budget": budget,
        }

    result = trash_path(str(target), reason=reason)
    return result


def _register_event(event_type: str, data: dict) -> None:
    try:
        from triade.core.run_system_events import register_system_event
        register_system_event(event_type, {**data, "source": EVENT_SOURCE})
    except ImportError:
        pass
