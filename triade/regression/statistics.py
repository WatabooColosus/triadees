"""Comparación estadística básica para múltiples ejecuciones reproducibles."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from statistics import fmean, stdev
from typing import Any, Iterable, Literal

StatisticalDecision = Literal["pass", "warn", "fail", "invalid"]


@dataclass(frozen=True, slots=True)
class StatisticalPolicy:
    metric_id: str
    min_samples: int = 3
    confidence_z: float = 1.96
    max_mean_drop: float = 0.0
    max_standard_error: float | None = None
    critical: bool = True

    def __post_init__(self) -> None:
        if not self.metric_id.strip():
            raise ValueError("metric_id es obligatorio")
        if self.min_samples < 2:
            raise ValueError("min_samples debe ser al menos 2")
        if self.confidence_z <= 0:
            raise ValueError("confidence_z debe ser positivo")
        if self.max_mean_drop < 0:
            raise ValueError("max_mean_drop no puede ser negativo")
        if self.max_standard_error is not None and self.max_standard_error < 0:
            raise ValueError("max_standard_error no puede ser negativo")


@dataclass(frozen=True, slots=True)
class StatisticalComparison:
    metric_id: str
    baseline_samples: int
    candidate_samples: int
    baseline_mean: float | None
    candidate_mean: float | None
    mean_delta: float | None
    baseline_stddev: float | None
    candidate_stddev: float | None
    standard_error: float | None
    confidence_low: float | None
    confidence_high: float | None
    decision: StatisticalDecision
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StatisticalRegressionAnalyzer:
    """Evalúa si una diferencia media es estable y suficiente."""

    @staticmethod
    def compare(
        *,
        baseline_scores: Iterable[float],
        candidate_scores: Iterable[float],
        policy: StatisticalPolicy,
    ) -> StatisticalComparison:
        baseline = tuple(float(value) for value in baseline_scores)
        candidate = tuple(float(value) for value in candidate_scores)
        if len(baseline) < policy.min_samples or len(candidate) < policy.min_samples:
            return StatisticalComparison(
                metric_id=policy.metric_id,
                baseline_samples=len(baseline),
                candidate_samples=len(candidate),
                baseline_mean=None,
                candidate_mean=None,
                mean_delta=None,
                baseline_stddev=None,
                candidate_stddev=None,
                standard_error=None,
                confidence_low=None,
                confidence_high=None,
                decision="invalid",
                reason="muestras insuficientes para comparación estadística",
            )
        baseline_mean = fmean(baseline)
        candidate_mean = fmean(candidate)
        baseline_sd = stdev(baseline)
        candidate_sd = stdev(candidate)
        standard_error = math.sqrt(
            (baseline_sd**2 / len(baseline)) + (candidate_sd**2 / len(candidate))
        )
        mean_delta = candidate_mean - baseline_mean
        margin = policy.confidence_z * standard_error
        confidence_low = mean_delta - margin
        confidence_high = mean_delta + margin
        if policy.max_standard_error is not None and standard_error > policy.max_standard_error:
            decision: StatisticalDecision = "warn"
            reason = "variabilidad superior al máximo permitido"
        elif confidence_high < -policy.max_mean_drop:
            decision = "fail" if policy.critical else "warn"
            reason = "el intervalo de confianza confirma una regresión media"
        elif confidence_low <= -policy.max_mean_drop:
            decision = "warn"
            reason = "resultado estadísticamente inconcluso"
        else:
            decision = "pass"
            reason = "no se detecta regresión media significativa"
        return StatisticalComparison(
            metric_id=policy.metric_id,
            baseline_samples=len(baseline),
            candidate_samples=len(candidate),
            baseline_mean=baseline_mean,
            candidate_mean=candidate_mean,
            mean_delta=mean_delta,
            baseline_stddev=baseline_sd,
            candidate_stddev=candidate_sd,
            standard_error=standard_error,
            confidence_low=confidence_low,
            confidence_high=confidence_high,
            decision=decision,
            reason=reason,
        )
