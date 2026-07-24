"""PlanRollback: rollback a nivel de plan.

Registra qué pasos fueron exitosos y cuáles fallaron,
y puede revertir efectos parciales de pasos completados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class RollbackAction:
    """Acción de reversión para un paso fallido."""

    step_id: str
    action_type: str = "none"
    description: str = ""
    reversible: bool = False
    applied: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action_type": self.action_type,
            "description": self.description,
            "reversible": self.reversible,
            "applied": self.applied,
            "error": self.error,
        }


@dataclass(slots=True)
class PlanRollback:
    """Gestor de rollback para un plan completo."""

    plan_id: str = ""
    rollback_stack: list[RollbackAction] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def register_step(
        self,
        *,
        step_id: str,
        action_type: str = "none",
        description: str = "",
        reversible: bool = False,
    ) -> None:
        self.rollback_stack.append(RollbackAction(
            step_id=step_id,
            action_type=action_type,
            description=description,
            reversible=reversible,
        ))

    def can_rollback(self) -> bool:
        return any(a.reversible and not a.applied for a in self.rollback_stack)

    def pending_reversals(self) -> list[RollbackAction]:
        return [a for a in self.rollback_stack if a.reversible and not a.applied]

    def mark_applied(self, step_id: str) -> None:
        for action in self.rollback_stack:
            if action.step_id == step_id:
                action.applied = True

    def failed_steps(self) -> list[str]:
        return [a.step_id for a in self.rollback_stack if a.action_type == "failed"]

    def completed_steps(self) -> list[str]:
        return [a.step_id for a in self.rollback_stack if a.action_type != "failed"]

    def rollback_summary(self) -> dict[str, Any]:
        total = len(self.rollback_stack)
        completed = len([a for a in self.rollback_stack if a.action_type != "failed"])
        failed = len([a for a in self.rollback_stack if a.action_type == "failed"])
        pending = len(self.pending_reversals())
        return {
            "plan_id": self.plan_id,
            "total_steps": total,
            "completed": completed,
            "failed": failed,
            "pending_reversals": pending,
            "can_rollback": self.can_rollback(),
        }

    def execute_rollback(self, *, max_steps: int = 5) -> list[dict[str, Any]]:
        """Ejecuta rollback reversible de los pasos más recientes primero.

        En la práctica, la reversión real depende del tipo de paso.
        Pasos de análisis/observación no requieren reversión.
        Pasos de archivo/delegación pueden requerir limpieza.
        """
        results = []
        pending = list(reversed(self.pending_reversals()))[:max_steps]
        for action in pending:
            success = self._apply_rollback(action)
            results.append({
                "step_id": action.step_id,
                "action_type": action.action_type,
                "applied": success,
                "description": action.description,
            })
            if success:
                action.applied = True
        return results

    def _apply_rollback(self, action: RollbackAction) -> bool:
        if action.action_type == "observation":
            return True
        if action.action_type == "analysis":
            return True
        if action.action_type == "delegation":
            action.error = "Delegation rollback requires external cleanup"
            return False
        return True
