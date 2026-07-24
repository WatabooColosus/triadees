"""Replanner: detecta fallo en un plan y genera estrategia de replanificación.

No re-ejecuta: solo analiza el fallo y propone un plan revisado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now
from .plan_step import PlanStep


@dataclass(slots=True)
class FailureAnalysis:
    """Análisis de por qué un plan falló."""

    step_id: str = ""
    error: str = ""
    failure_type: str = "unknown"
    recoverable: bool = True
    root_cause: str = ""
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "error": self.error,
            "failure_type": self.failure_type,
            "recoverable": self.recoverable,
            "root_cause": self.root_cause,
            "suggested_fix": self.suggested_fix,
        }


@dataclass(slots=True)
class ReplanificationStrategy:
    """Estrategia propuesta tras un fallo."""

    strategy: str = "retry"
    modified_steps: list[dict[str, Any]] = field(default_factory=list)
    removed_steps: list[str] = field(default_factory=list)
    added_steps: list[dict[str, Any]] = field(default_factory=list)
    risk_assessment: str = "low"
    rationale: str = ""
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "modified_steps": list(self.modified_steps),
            "removed_steps": list(self.removed_steps),
            "added_steps": list(self.added_steps),
            "risk_assessment": self.risk_assessment,
            "rationale": self.rationale,
            "created_at": self.created_at,
        }


FAILURE_TYPES = {
    "timeout": "timeout",
    "model_error": "model_error",
    "resource_exhaustion": "resource_exhaustion",
    "safety_block": "safety_block",
    "dependency_missing": "dependency_missing",
    "permission_denied": "permission_denied",
    "unknown": "unknown",
}

STRATEGY_MAP = {
    "timeout": "skip_and_continue",
    "model_error": "retry_with_fallback",
    "resource_exhaustion": "pause_and_reduce",
    "safety_block": "abort_plan",
    "dependency_missing": "skip_and_continue",
    "permission_denied": "skip_and_continue",
    "unknown": "retry",
}


class Replanner:
    """Analiza fallos de plan y genera estrategias de replanificación."""

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    def analyze_failure(
        self,
        *,
        step: PlanStep,
        error: str,
        context: dict[str, Any] | None = None,
    ) -> FailureAnalysis:
        failure_type = self._classify_error(error, context or {})
        root_cause = self._guess_root_cause(failure_type, error, context or {})
        recoverable = failure_type not in {"safety_block", "permission_denied"}

        return FailureAnalysis(
            step_id=step.id,
            error=error,
            failure_type=failure_type,
            recoverable=recoverable,
            root_cause=root_cause,
            suggested_fix=self._suggest_fix(failure_type, step),
        )

    def build_strategy(
        self,
        *,
        analysis: FailureAnalysis,
        remaining_steps: list[PlanStep],
        budget_remaining: dict[str, Any] | None = None,
    ) -> ReplanificationStrategy:
        strategy = STRATEGY_MAP.get(analysis.failure_type, "retry")
        budget_ok = True
        if budget_remaining:
            budget_ok = budget_remaining.get("remaining_steps", 10) > 2

        if strategy == "abort_plan" or not analysis.recoverable:
            return ReplanificationStrategy(
                strategy="abort",
                risk_assessment="high",
                rationale=f"Paso {analysis.step_id} falló de forma no recuperable: {analysis.failure_type}.",
            )

        if strategy == "retry_with_fallback" and analysis.step_id:
            return ReplanificationStrategy(
                strategy="retry",
                modified_steps=[{
                    "step_id": analysis.step_id,
                    "fallback": True,
                    "use_template": True,
                }],
                risk_assessment="low",
                rationale="Reintentar con fallback a plantilla ante error de modelo.",
            )

        if strategy == "skip_and_continue":
            ready_after = [
                s.to_dict() for s in remaining_steps
                if analysis.step_id not in s.dependencies
            ]
            return ReplanificationStrategy(
                strategy="skip_and_continue",
                removed_steps=[analysis.step_id],
                modified_steps=ready_after[:3],
                risk_assessment="medium",
                rationale=f"Omitir paso {analysis.step_id} y continuar con pasos disponibles.",
            )

        if strategy == "pause_and_reduce":
            return ReplanificationStrategy(
                strategy="pause",
                risk_assessment="medium",
                rationale="Recursos agotados. Pausar y reducir alcance del plan.",
            )

        return ReplanificationStrategy(
            strategy="retry",
            modified_steps=[{"step_id": analysis.step_id, "attempt": "retry"}],
            risk_assessment="low",
            rationale=f"Reintentar paso {analysis.step_id} ({analysis.failure_type}).",
        )

    def _classify_error(self, error: str, context: dict[str, Any]) -> str:
        err = error.lower()
        if "timeout" in err or "timed out" in err:
            return "timeout"
        if "ollama" in err or "model" in err or "generate" in err:
            return "model_error"
        if "memory" in err or "ram" in err or "oom" in err:
            return "resource_exhaustion"
        if "safety" in err or "blocked" in err or "constitution" in err:
            return "safety_block"
        if "permission" in err or "forbidden" in err:
            return "permission_denied"
        if "import" in err or "module" in err or "not found" in err:
            return "dependency_missing"
        return "unknown"

    def _guess_root_cause(self, failure_type: str, error: str, context: dict[str, Any]) -> str:
        if failure_type == "model_error":
            return "Ollama no disponible o modelo sobrecargado"
        if failure_type == "timeout":
            return "El paso excedió el tiempo máximo permitido"
        if failure_type == "resource_exhaustion":
            return "Recursos del sistema insuficientes"
        if failure_type == "safety_block":
            return "La Constitución o Safety bloquearon la operación"
        return f"Error no clasificado: {error[:100]}"

    def _suggest_fix(self, failure_type: str, step: PlanStep) -> str:
        if failure_type == "model_error":
            return "Usar fallback de plantilla o modelo alternativo"
        if failure_type == "timeout":
            return "Reducir alcance o dividir en sub-pasos"
        if failure_type == "resource_exhaustion":
            return "Reducir tokens o pausar ejecución"
        if failure_type == "safety_block":
            return "Revisar política de Constitución"
        return "Revisar logs y reintentar"
