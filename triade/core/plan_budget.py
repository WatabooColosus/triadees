"""PlanBudget: presupuestos de plan (tiempo, tokens, recursos).

Controla cuánto puede gastar un plan en cada dimensión.
Si el presupuesto se agota, el plan debe pausarse o replanificarse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now


@dataclass(slots=True)
class PlanBudget:
    """Presupuesto asignado a un plan completo."""

    max_total_seconds: float = 120.0
    max_tokens: int = 8192
    max_steps: int = 20
    max_retries: int = 3
    max_cost_usd: float = 0.10
    used_seconds: float = 0.0
    used_tokens: int = 0
    used_steps: int = 0
    used_retries: int = 0
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_total_seconds": self.max_total_seconds,
            "max_tokens": self.max_tokens,
            "max_steps": self.max_steps,
            "max_retries": self.max_retries,
            "max_cost_usd": self.max_cost_usd,
            "used_seconds": round(self.used_seconds, 3),
            "used_tokens": self.used_tokens,
            "used_steps": self.used_steps,
            "used_retries": self.used_retries,
            "remaining_seconds": round(max(0, self.max_total_seconds - self.used_seconds), 3),
            "remaining_tokens": max(0, self.max_tokens - self.used_tokens),
            "remaining_steps": max(0, self.max_steps - self.used_steps),
        }

    def can_proceed(self) -> bool:
        return (
            self.used_seconds < self.max_total_seconds
            and self.used_tokens < self.max_tokens
            and self.used_steps < self.max_steps
        )

    def exhausted_reason(self) -> str:
        reasons = []
        if self.used_seconds >= self.max_total_seconds:
            reasons.append("timeout")
        if self.used_tokens >= self.max_tokens:
            reasons.append("token_limit")
        if self.used_steps >= self.max_steps:
            reasons.append("step_limit")
        return ", ".join(reasons) if reasons else ""

    def consume_step(self, *, seconds: float = 0.0, tokens: int = 0) -> None:
        self.used_seconds += seconds
        self.used_tokens += tokens
        self.used_steps += 1

    def consume_retry(self) -> bool:
        if self.used_retries < self.max_retries:
            self.used_retries += 1
            return True
        return False

    def utilization(self) -> dict[str, float]:
        return {
            "time_pct": round(self.used_seconds / max(1, self.max_total_seconds) * 100, 1),
            "token_pct": round(self.used_tokens / max(1, self.max_tokens) * 100, 1),
            "step_pct": round(self.used_steps / max(1, self.max_steps) * 100, 1),
        }

    @classmethod
    def for_intent(cls, intent: str, q_crystal: float = 0.5) -> PlanBudget:
        """Crea un presupuesto razonable según la intención y el estado del Cristal."""
        base = cls()
        if intent == "build_or_update":
            base.max_total_seconds = 180.0
            base.max_tokens = 12288
            base.max_steps = 25
        elif intent == "analyze":
            base.max_total_seconds = 90.0
            base.max_tokens = 6144
            base.max_steps = 15
        elif intent == "conversation":
            base.max_total_seconds = 60.0
            base.max_tokens = 4096
            base.max_steps = 10
        if q_crystal < 0.40:
            base.max_steps = min(base.max_steps, 8)
            base.max_retries = 1
        return base
