"""Contratos de medición reproducible para Tríade Ω."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Decision = Literal["improved", "neutral", "regressed", "invalid"]


def _bounded_score(value: float) -> float:
    score = float(value)
    if not 0.0 <= score <= 1.0:
        raise ValueError("score debe estar entre 0.0 y 1.0")
    return score


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    capability: str
    input_payload: dict[str, Any]
    expected: Any
    weight: float = 1.0
    critical: bool = False
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_id.strip():
            raise ValueError("case_id es obligatorio")
        if not self.capability.strip():
            raise ValueError("capability es obligatoria")
        if self.weight <= 0:
            raise ValueError("weight debe ser mayor que cero")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BenchmarkSuite:
    suite_id: str
    version: str
    capability: str
    cases: tuple[BenchmarkCase, ...]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.suite_id.strip() or not self.version.strip():
            raise ValueError("suite_id y version son obligatorios")
        if not self.cases:
            raise ValueError("la suite debe contener al menos un caso")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case_id duplicado en la suite")
        if any(case.capability != self.capability for case in self.cases):
            raise ValueError("todos los casos deben pertenecer a la capacidad de la suite")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MetricResult:
    case_id: str
    score: float
    passed: bool
    actual: Any
    expected: Any
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "score", _bounded_score(self.score))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvaluationRun:
    evaluation_id: str
    suite_id: str
    suite_version: str
    subject_id: str
    results: tuple[MetricResult, ...]
    aggregate_score: float
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "aggregate_score", _bounded_score(self.aggregate_score))
        if not self.results:
            raise ValueError("EvaluationRun requiere resultados")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapabilityBaseline:
    baseline_id: str
    capability: str
    suite_id: str
    suite_version: str
    subject_id: str
    aggregate_score: float
    evaluation_id: str
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "aggregate_score", _bounded_score(self.aggregate_score))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EvaluationComparison:
    baseline_evaluation_id: str
    candidate_evaluation_id: str
    baseline_score: float
    candidate_score: float
    absolute_delta: float
    percent_delta: float | None
    improved_cases: tuple[str, ...]
    degraded_cases: tuple[str, ...]
    critical_regressions: tuple[str, ...]
    decision: Decision

    def __post_init__(self) -> None:
        object.__setattr__(self, "baseline_score", _bounded_score(self.baseline_score))
        object.__setattr__(self, "candidate_score", _bounded_score(self.candidate_score))
        if self.decision not in {"improved", "neutral", "regressed", "invalid"}:
            raise ValueError("decision inválida")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
