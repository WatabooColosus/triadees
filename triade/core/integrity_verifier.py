"""Integrity Verifier · snapshots before/after y detección de cambios no planeados."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triade.core.system_zones import classify_path, REPO_ROOT

CHUNK_SIZE = 65536


def _hash_path(p: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
    except (OSError, PermissionError):
        return ""
    return h.hexdigest()


def _file_info(p: Path, zone: str) -> dict[str, Any]:
    try:
        st = p.stat()
        return {
            "path": str(p),
            "relative_path": str(p.relative_to(REPO_ROOT)),
            "sha256": _hash_path(p),
            "size": st.st_size,
            "created_at": datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat(),
            "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "exists": True,
            "zone": zone,
        }
    except (OSError, PermissionError):
        return {
            "path": str(p), "relative_path": "", "sha256": "",
            "size": 0, "created_at": "", "modified_at": "", "exists": False, "zone": zone,
        }


def build_integrity_snapshot(paths: list[str] | None = None) -> dict[str, Any]:
    """Toma snapshot de integridad de archivos.

    Si paths=None, escanea todo el repo (excluyendo .git, __pycache__, node_modules).
    """
    repo = REPO_ROOT
    files: dict[str, dict] = {}
    total_bytes = 0

    if paths:
        targets = [Path(p).resolve() for p in paths if Path(p).exists()]
    else:
        targets = []
        for root, dirs, fnames in os.walk(repo):
            rel = Path(root).relative_to(repo)
            parts = rel.parts
            if ".git" in parts or "__pycache__" in parts or "node_modules" in parts or ".triade_trash" in parts:
                dirs[:] = []
                continue
            for fname in fnames:
                fp = Path(root) / fname
                targets.append(fp)

    for fp in targets:
        try:
            rel = str(fp.relative_to(repo))
        except ValueError:
            continue
        zone = classify_path(rel).get("zone", "unknown")
        info = _file_info(fp, zone)
        files[rel] = info
        total_bytes += info["size"]

    return {
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "files_count": len(files),
        "total_bytes": total_bytes,
        "zone_summary": _zone_summary(files),
        "files": files,
    }


def _zone_summary(files: dict) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for rel, info in files.items():
        z = info.get("zone", "unknown")
        if z not in summary:
            summary[z] = {"count": 0, "bytes": 0}
        summary[z]["count"] += 1
        summary[z]["bytes"] += info.get("size", 0)
    return summary


def verify_integrity_change(
    before: dict[str, Any],
    after: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Verifica cambio de integridad entre before y after contra un plan.

    Args:
        before: snapshot pre-ejecución.
        after: snapshot post-ejecución.
        plan: plan de acción (debe tener target_paths, action_type, allowed_zones, etc.).

    Returns dict con status, created_files, modified_files, moved_files,
            trashed_files, missing_unexpected, hash_changed_unexpected,
            bytes_delta, risk_score, requires_rollback, requires_human_review.
    """
    bf = before.get("files", {})
    af = after.get("files", {})
    raw = plan.get("target_paths", [])
    planned_rel: set[str] = set()
    repo = REPO_ROOT
    for p in raw:
        try:
            planned_rel.add(str(Path(p).relative_to(repo)))
        except (ValueError, TypeError):
            planned_rel.add(str(p))
    planned_action = plan.get("action_type", "read")

    created = []
    modified = []
    moved = []
    trashed = []
    missing_unexpected = []
    hash_changed_unexpected = []

    all_rels = set(bf.keys()) | set(af.keys())
    for rel in all_rels:
        b_info = bf.get(rel)
        a_info = af.get(rel)
        b_exists = b_info is not None and b_info.get("exists", False)
        a_exists = a_info is not None and a_info.get("exists", False)

        if not b_exists and a_exists:
            if rel in planned_rel and planned_action in ("create", "move", "patch"):
                created.append(rel)
            else:
                hash_changed_unexpected.append({"rel": rel, "reason": "Archivo creado no planeado."})
        elif b_exists and not a_exists:
            if rel in planned_rel and planned_action in ("delete_to_trash", "move"):
                trashed.append(rel)
            else:
                missing_unexpected.append(rel)
        elif b_exists and a_exists:
            if b_info.get("sha256") != a_info.get("sha256"):
                if rel in planned_rel and planned_action in ("patch", "move", "create"):
                    modified.append(rel)
                else:
                    hash_changed_unexpected.append({"rel": rel, "reason": "Hash cambiado no planeado."})

    bytes_delta = after.get("total_bytes", 0) - before.get("total_bytes", 0)
    max_budget = plan.get("max_bytes_per_cycle", 0)
    risk_score = _calc_risk_score(
        len(hash_changed_unexpected), len(missing_unexpected),
        bytes_delta, max_budget, planned_rel, plan,
    )

    requires_rollback = risk_score > 0.6 or len(missing_unexpected) > 0
    requires_human_review = risk_score > 0.4 or len(hash_changed_unexpected) > 0

    return {
        "status": "failed" if (requires_rollback or len(hash_changed_unexpected) > 0 or len(missing_unexpected) > 0) else "ok",
        "created_files": created,
        "modified_files": modified,
        "moved_files": moved,
        "trashed_files": trashed,
        "missing_unexpected": missing_unexpected,
        "hash_changed_unexpected": hash_changed_unexpected,
        "bytes_delta": bytes_delta,
        "risk_score": round(risk_score, 2),
        "requires_rollback": requires_rollback,
        "requires_human_review": requires_human_review,
        "summary": _build_summary(created, modified, trashed, missing_unexpected, hash_changed_unexpected),
    }


def _calc_risk_score(
    unplanned_hashes: int, missing: int, delta: int, max_bytes: int,
    planned: set, plan: dict,
) -> float:
    score = 0.0
    if unplanned_hashes > 0:
        score += 0.4
    if missing > 0:
        score += 0.5
    if max_bytes > 0 and abs(delta) > max_bytes:
        score += 0.3
    zones = set(plan.get("zones", []))
    if "red" in zones:
        score += 0.3
    if len(planned) == 0:
        score += 0.1
    return min(score, 1.0)


def _build_summary(created, modified, trashed, missing, unplanned):
    parts = []
    if created:
        parts.append(f"{len(created)} creados")
    if modified:
        parts.append(f"{len(modified)} modificados")
    if trashed:
        parts.append(f"{len(trashed)} movidos a papelera")
    if missing:
        parts.append(f"{len(missing)} faltantes no planeados")
    if unplanned:
        parts.append(f"{len(unplanned)} cambios hash no planeados")
    return ", ".join(parts) if parts else "Sin cambios detectados."
