"""Delegated Action Planner · planea acciones delegadas sin ejecutarlas."""

from __future__ import annotations

from typing import Any

from triade.core.autonomy_budget import build_autonomy_budget
from triade.core.system_zones import classify_path

INTENT_CLASSIFICATION = {
    "read": {"actions": ["read"], "risk": 0.0},
    "create": {"actions": ["create"], "risk": 0.2},
    "patch": {"actions": ["patch"], "risk": 0.3},
    "move": {"actions": ["move"], "risk": 0.4},
    "delete": {"actions": ["delete_to_trash"], "risk": 0.5},
    "organize": {"actions": ["move", "create", "delete_to_trash"], "risk": 0.5},
    "refactor": {"actions": ["patch", "move", "create", "delete_to_trash", "run_tests", "run_build"], "risk": 0.7},
    "test": {"actions": ["run_tests"], "risk": 0.3},
    "build": {"actions": ["run_build"], "risk": 0.3},
    "read_only": {"actions": ["read"], "risk": 0.0},
}


def _classify_intent(intent: str) -> dict[str, Any]:
    intent = intent.strip().lower()
    for key, val in INTENT_CLASSIFICATION.items():
        if intent == key or intent.startswith(key):
            return {"intent": key, **val}
    return {"intent": "read", "actions": ["read"], "risk": 0.0}


def plan_delegated_action(
    intent: str, requested_paths: list[str], autonomy_level: str,
) -> dict[str, Any]:
    """Planea una acción delegada sin ejecutarla.

    Args:
        intent: read/create/patch/move/delete/organize/refactor/test/build.
        requested_paths: lista de rutas objetivo.
        autonomy_level: nivel de autonomía.

    Returns:
        Dict con plan detallado.
    """
    intent_info = _classify_intent(intent)
    budget = build_autonomy_budget(autonomy_level)

    zones = []
    forbidden = []
    red = []
    yellow = []
    green = []
    human_approval_required = False
    blocked_reason = None

    for p in requested_paths:
        info = classify_path(p)
        z = info["zone"]
        zones.append(z)
        if z == "forbidden":
            forbidden.append(p)
            blocked_reason = f"Ruta prohibida: {p}"
        elif z == "red":
            red.append(p)
            human_approval_required = True
        elif z == "yellow":
            yellow.append(p)
        else:
            green.append(p)

    zones = list(set(zones))

    # Verificar acciones permitidas por budget
    allowed_actions_set = set(budget.get("allowed_actions", []))
    required_actions = set(intent_info["actions"])
    blocked_actions = required_actions - allowed_actions_set
    if blocked_actions and blocked_reason is None:
        blocked_reason = f"Acciones no permitidas por nivel {autonomy_level}: {', '.join(sorted(blocked_actions))}"

    if forbidden and blocked_reason is None:
        blocked_reason = "Ruta en zona prohibida."

    # Si hay rutas rojas y la acción no es read-only
    if red and intent_info["intent"] != "read":
        human_approval_required = True

    if len(requested_paths) > budget.get("max_files_per_cycle", 0):
        blocked_reason = blocked_reason or f"Supera máximo de archivos por ciclo ({budget['max_files_per_cycle']})"

    risk_score = intent_info["risk"]
    if red:
        risk_score = min(risk_score + 0.3, 1.0)
    if forbidden:
        risk_score = 1.0

    plan = {
        "action_type": intent_info["intent"],
        "actions": intent_info["actions"],
        "target_paths": requested_paths,
        "zones": zones,
        "forbidden_zones": forbidden,
        "red_zones": red,
        "yellow_zones": yellow,
        "green_zones": green,
        "risk_score": round(risk_score, 2),
        "dry_run_required": risk_score > 0.3,
        "tests_required": "run_tests" in intent_info["actions"],
        "build_required": "run_build" in intent_info["actions"],
        "human_approval_required": human_approval_required,
        "allowed": blocked_reason is None,
        "blocked_reason": blocked_reason,
        "autonomy_level": autonomy_level,
        "autonomy_percent": budget.get("autonomy_percent", 0),
        "budget": {
            "max_files_per_cycle": budget["max_files_per_cycle"],
            "max_bytes_per_cycle": budget["max_bytes_per_cycle"],
        },
    }

    return plan
