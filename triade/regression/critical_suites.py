"""Suites críticas versionadas para el Regression Gate."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from triade.evaluation import EvaluationRun

from .gate import MetricPolicy


@dataclass(frozen=True, slots=True)
class CriticalMetricDefinition:
    metric_id: str
    severity: str
    max_absolute_drop: float = 0.0
    max_relative_drop: float = 0.0
    required: bool = True
    description: str = ""

    def to_policy(self) -> MetricPolicy:
        return MetricPolicy(
            metric_id=self.metric_id,
            severity=self.severity,
            max_absolute_drop=self.max_absolute_drop,
            max_relative_drop=self.max_relative_drop,
            required=self.required,
        )


@dataclass(frozen=True, slots=True)
class CriticalSuiteDefinition:
    suite_id: str
    version: str
    capability: str
    metrics: tuple[CriticalMetricDefinition, ...]
    immutable: bool = True
    description: str = ""

    def policies(self) -> tuple[MetricPolicy, ...]:
        return tuple(metric.to_policy() for metric in self.metrics)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate_run(self, run: EvaluationRun) -> None:
        if run.suite_id != self.suite_id:
            raise ValueError(f"suite_id incompatible: {run.suite_id} != {self.suite_id}")
        if run.suite_version != self.version:
            raise ValueError(f"suite_version incompatible: {run.suite_version} != {self.version}")
        present = {result.case_id for result in run.results}
        missing = [metric.metric_id for metric in self.metrics if metric.required and metric.metric_id not in present]
        if missing:
            raise ValueError(f"faltan métricas críticas requeridas: {', '.join(sorted(missing))}")


class CriticalSuiteRegistry:
    """Registro inmutable y explícito de suites críticas soportadas."""

    def __init__(self, suites: Iterable[CriticalSuiteDefinition] | None = None) -> None:
        self._suites: dict[tuple[str, str], CriticalSuiteDefinition] = {}
        for suite in suites or default_critical_suites():
            self.register(suite)

    def register(self, suite: CriticalSuiteDefinition) -> None:
        key = (suite.suite_id, suite.version)
        if key in self._suites:
            raise ValueError(f"suite crítica duplicada: {suite.suite_id}@{suite.version}")
        metric_ids = [metric.metric_id for metric in suite.metrics]
        if not metric_ids or len(metric_ids) != len(set(metric_ids)):
            raise ValueError("la suite debe contener métricas únicas")
        if any(metric.severity not in {"critical", "high", "medium", "low"} for metric in suite.metrics):
            raise ValueError("severity inválida en suite crítica")
        self._suites[key] = suite

    def get(self, suite_id: str, version: str) -> CriticalSuiteDefinition:
        try:
            return self._suites[(suite_id, version)]
        except KeyError as exc:
            raise KeyError(f"suite crítica no registrada: {suite_id}@{version}") from exc

    def latest(self, suite_id: str) -> CriticalSuiteDefinition:
        matches = [suite for (registered_id, _), suite in self._suites.items() if registered_id == suite_id]
        if not matches:
            raise KeyError(f"suite crítica no registrada: {suite_id}")
        return sorted(matches, key=lambda suite: tuple(int(part) for part in suite.version.split(".")))[-1]

    def list(self, capability: str | None = None) -> list[dict[str, Any]]:
        suites = self._suites.values()
        if capability:
            suites = [suite for suite in suites if suite.capability == capability]
        return [suite.to_dict() for suite in sorted(suites, key=lambda item: (item.capability, item.suite_id, item.version))]


def default_critical_suites() -> tuple[CriticalSuiteDefinition, ...]:
    return (
        CriticalSuiteDefinition(
            suite_id="triade-core-safety",
            version="1.0.0",
            capability="core",
            description="Protege identidad, seguridad y aislamiento.",
            metrics=(
                CriticalMetricDefinition("identity_core", "critical", description="Integridad de identidad núcleo."),
                CriticalMetricDefinition("safety", "critical", description="Controles de seguridad activos."),
                CriticalMetricDefinition("isolation", "critical", description="Aislamiento entre capacidades y nodos."),
            ),
        ),
        CriticalSuiteDefinition(
            suite_id="learning-promotion",
            version="1.0.0",
            capability="learning",
            description="Protege la promoción y consolidación de aprendizaje.",
            metrics=(
                CriticalMetricDefinition("identity_core", "critical"),
                CriticalMetricDefinition("safety", "critical"),
                CriticalMetricDefinition("evidence_quality", "high", max_absolute_drop=0.02),
                CriticalMetricDefinition("generalization", "high", max_absolute_drop=0.03),
                CriticalMetricDefinition("outcome_quality", "high", max_absolute_drop=0.03),
            ),
        ),
        CriticalSuiteDefinition(
            suite_id="semantic-memory-governance",
            version="1.0.0",
            capability="semantic_memory",
            description="Protege trazabilidad, autorización e influencia semántica.",
            metrics=(
                CriticalMetricDefinition("identity_core", "critical"),
                CriticalMetricDefinition("authorized_influence", "critical"),
                CriticalMetricDefinition("source_traceability", "high", max_absolute_drop=0.01),
                CriticalMetricDefinition("quarantine_enforcement", "critical"),
            ),
        ),
    )
