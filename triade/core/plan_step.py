"""PlanStep: paso estructurado de un plan de Central.

Reemplaza la lista de strings por un dataclass con tipo, prioridad,
dependencias y estado. Retrocompatible: PlanStep.to_dict() produce
un dict que Central puede leer como string si necesita.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class PlanStep:
    """Paso estructurado de un plan cognitivo."""

    id: str = ""
    description: str = ""
    step_type: str = "action"
    priority: int = 3
    status: str = "pending"
    dependencies: list[str] = field(default_factory=list)
    assigned_to: str = "central"
    timeout_seconds: float = 30.0
    max_retries: int = 1
    retry_count: int = 0
    error_message: str = ""
    started_at: str = ""
    completed_at: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "step_type": self.step_type,
            "priority": self.priority,
            "status": self.status,
            "dependencies": list(self.dependencies),
            "assigned_to": self.assigned_to,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": dict(self.result),
            "metadata": dict(self.metadata),
        }

    def to_text(self) -> str:
        """Representación textual legacy para retrocompatibilidad."""
        prefix = ""
        if self.assigned_to != "central":
            prefix = f"[→{self.assigned_to}] "
        return f"{prefix}{self.description}"

    def start(self) -> None:
        self.status = "running"
        self.started_at = utc_now()

    def complete(self, result: dict[str, Any] | None = None) -> None:
        self.status = "completed"
        self.completed_at = utc_now()
        if result:
            self.result = result

    def fail(self, error: str) -> None:
        self.status = "failed"
        self.error_message = error

    def retry(self) -> bool:
        if self.retry_count < self.max_retries:
            self.retry_count += 1
            self.status = "pending"
            self.error_message = ""
            return True
        return False

    def is_ready(self, completed_ids: set[str]) -> bool:
        return self.status == "pending" and all(d in completed_ids for d in self.dependencies)


STEP_TYPES = {"action", "analysis", "delegation", "verification", "rollback", "observation"}
STEP_STATUSES = {"pending", "running", "completed", "failed", "skipped"}
