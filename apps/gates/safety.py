from __future__ import annotations

import threading
from typing import Any

from fastapi import HTTPException, status

BLOCKED_STATUSES = frozenset({"blocked"})
HUMAN_APPROVAL_STATUSES = frozenset({"requires_human_approval"})

_pending_lock = threading.Lock()
_pending_approvals: dict[str, dict[str, Any]] = {}


def get_pending_approvals() -> dict[str, dict[str, Any]]:
    with _pending_lock:
        return dict(_pending_approvals)


def store_pending_approval(result: dict[str, Any]) -> None:
    run_id = result.get("run_id", "unknown")
    with _pending_lock:
        _pending_approvals[run_id] = result


def remove_pending_approval(run_id: str) -> dict[str, Any] | None:
    with _pending_lock:
        return _pending_approvals.pop(run_id, None)


def safety_gate(result: dict[str, Any]) -> dict[str, Any]:
    safety = result.get("safety", {})
    status_val = safety.get("status")
    risk_level = safety.get("risk_level", "low")
    human_approval = safety.get("human_approval_required", False)
    reason = safety.get("reason", "")
    controls = safety.get("required_controls", [])

    if status_val in BLOCKED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Acción bloqueada por Safety Gate.",
                "risk_level": risk_level,
                "reason": reason,
                "required_controls": controls,
                "truth": "Safety Gate bloqueó la ejecución. Revisa reason y controls.",
            },
        )

    if human_approval or status_val in HUMAN_APPROVAL_STATUSES:
        store_pending_approval(result)
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "error": "Se requiere aprobación humana antes de ejecutar.",
                "risk_level": risk_level,
                "reason": reason,
                "required_controls": controls,
                "run_id": safety.get("run_id"),
                "approval_endpoint": "/api/safety/approve",
                "truth": (
                    "El run se completó pero Safety requiere aprobación humana. "
                    "Usa /api/safety/approve para autorizar."
                ),
            },
        )

    return result
