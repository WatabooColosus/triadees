from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

BLOCKED_STATUSES = frozenset({"blocked"})


def safety_gate(result: dict[str, Any]) -> dict[str, Any]:
    safety = result.get("safety", {})
    status_val = safety.get("status")
    risk_level = safety.get("risk_level", "low")
    reason = safety.get("reason", "")
    controls = safety.get("required_controls", [])

    if status_val in BLOCKED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Acción bloqueada por Safety.",
                "risk_level": risk_level,
                "reason": reason,
                "required_controls": controls,
            },
        )

    return result
