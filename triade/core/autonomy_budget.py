"""Autonomy Budget · niveles de autonomía delegada con presupuesto."""

from __future__ import annotations

from typing import Any

LEVELS = [
    "observe_only",
    "safe_write",
    "project_maintenance",
    "repo_refactor",
    "full_local_guarded",
]

LEVEL_PERCENT = {
    "observe_only": 0,
    "safe_write": 20,
    "project_maintenance": 45,
    "repo_refactor": 65,
    "full_local_guarded": 80,
}


def build_autonomy_budget(level: str) -> dict[str, Any]:
    """Construye presupuesto de autonomía para el nivel dado."""
    level = level.strip().lower() if level else "observe_only"
    if level not in LEVEL_PERCENT:
        level = "observe_only"

    pct = LEVEL_PERCENT[level]

    base = {
        "level": level,
        "autonomy_percent": pct,
        "max_files_per_cycle": _max_files(pct),
        "max_bytes_per_cycle": _max_bytes(pct),
        "allowed_zones": _allowed_zones(level),
        "allowed_actions": _allowed_actions(level),
        "forbidden_actions": _forbidden_actions(level),
        "requires_human_approval_for": _human_approval(level),
        "can_delete_directly": False,
        "delete_strategy": "trash_only",
        "can_modify_identity_core": False,
        "can_modify_git": False,
    }
    base["can_dry_run"] = pct > 0
    return base


def _max_files(pct: int) -> int:
    if pct == 0:
        return 0
    if pct <= 20:
        return 5
    if pct <= 45:
        return 15
    if pct <= 65:
        return 30
    return 50


def _max_bytes(pct: int) -> int:
    if pct == 0:
        return 0
    if pct <= 20:
        return 1024 * 50  # 50 KB
    if pct <= 45:
        return 1024 * 200  # 200 KB
    if pct <= 65:
        return 1024 * 1024  # 1 MB
    return 1024 * 1024 * 5  # 5 MB


def _allowed_zones(level: str) -> list[str]:
    if level == "observe_only":
        return ["green"]
    if level == "safe_write":
        return ["green"]
    if level == "project_maintenance":
        return ["green", "yellow"]
    if level == "repo_refactor":
        return ["green", "yellow"]
    if level == "full_local_guarded":
        return ["green", "yellow"]
    return []


def _allowed_actions(level: str) -> list[str]:
    base = ["read"]
    if level == "observe_only":
        return base
    base.append("create")
    if level in ("safe_write", "project_maintenance", "repo_refactor", "full_local_guarded"):
        base.append("patch")
        base.append("move")
        base.append("delete_to_trash")
    if level in ("project_maintenance", "repo_refactor", "full_local_guarded"):
        base.append("organize")
    if level in ("repo_refactor", "full_local_guarded"):
        base.append("refactor")
    if level == "full_local_guarded":
        base.append("run_tests")
        base.append("run_build")
        base.append("run_safe_shell")
    return base


def _forbidden_actions(level: str) -> list[str]:
    fb = ["delete_permanently", "modify_identity_core", "modify_git", "run_shell_free"]
    if level != "full_local_guarded":
        fb.extend(["run_tests", "run_build", "run_safe_shell"])
    if level in ("observe_only", "safe_write"):
        fb.extend(["patch", "move", "delete_to_trash", "organize", "refactor"])
    if level == "observe_only":
        fb.append("create")
    return sorted(fb)


def _human_approval(level: str) -> list[str]:
    appr = ["delete_permanently", "modify_identity_core", "modify_git", "run_shell_free"]
    if level != "full_local_guarded":
        appr.append("run_tests")
        appr.append("run_build")
    if level in ("observe_only", "safe_write", "project_maintenance"):
        appr.append("refactor_code")
        appr.append("delete_yellow_zone")
    if level == "observe_only":
        appr.append("create_file")
        appr.append("patch_file")
        appr.append("move_file")
        appr.append("delete_to_trash")
    return sorted(appr)
