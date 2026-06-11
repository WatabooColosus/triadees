"""Safety Gate — intercepta el flujo post-run según el nivel de riesgo."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

BLOCKED_STATUSES = frozenset({"blocked"})
HUMAN_APPROVAL_STATUSES = frozenset({"requires_human_approval"})


def safety_gate(result: dict[str, Any]) -> dict[str, Any]:
    """Post-run gate: evalúa SafetyPacket y bloquea si corresponde.

    Args:
        result: Diccionario devuelto por TriadeRunner.run().
                Debe contener la clave "safety" con los campos del SafetyPacket.

    Returns:
        El mismo result si el safety lo permite.

    Raises:
        HTTPException 403 si safety.status == "blocked".
        HTTPException 428 si human_approval_required.
    """
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
