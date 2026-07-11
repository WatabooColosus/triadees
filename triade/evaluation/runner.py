"""Runner determinista y comparador de Measurement Core."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.core.contracts import utc_now

from .contracts import (
    BenchmarkCase,
    BenchmarkSuite,
    CapabilityBaseline,
    EvaluationComparison,
    EvaluationRun,
    MetricResult,
)

Evaluator = Callable[[BenchmarkCase], Any]


class EvaluationRunner:
    """Ejecuta suites locales sin shell ni red y persiste evidencia JSON."""

    def __init__(self, runs_dir: str | Path = "runs/evaluations") -> None:
        self.runs_dir = Path(runs_dir)

    def run(
        self,
        suite: BenchmarkSuite,
        *,
        subject_id: str,
        evaluator: Evaluator,
        metadata: Mapping[str, Any] | None = None,
    ) -> EvaluationRun:
        if not subject_id.strip():
            raise ValueError("subject_id es obligatorio")
        results: list[MetricResult] = []
        total_weight = 0.0
        weighted_score = 0.0
        for case in suite.cases:
            actual = evaluator(case)
            score = 1.0 if actual == case.expected else 0.0
            result = MetricResult(
                case_id=case.case_id,
                score=score,
                passed=score == 1.0,
                actual=actual,
                expected=case.expected,
                details={"critical": case.critical, "weight": case.weight, "tags": list(case.tags)},
            )
            results.append(result)
            total_weight += case.weight
            weighted_score += score * case.weight

        aggregate = weighted_score / total_weight
        run = EvaluationRun(
            evaluation_id=f"eval-{uuid4().hex[:16]}",
            suite_id=suite.suite_id,
            suite_version=suite.version,
            subject_id=subject_id,
            results=tuple(results),
            aggregate_score=round(aggregate, 6),
            created_at=utc_now(),
            metadata=dict(metadata or {}),
        )
        self._persist(run, suite)
        return run

    def create_baseline(self, capability: str, run: EvaluationRun) -> CapabilityBaseline:
        baseline = CapabilityBaseline(
            baseline_id=f"baseline-{uuid4().hex[:16]}",
            capability=capability,
            suite_id=run.suite_id,
            suite_version=run.suite_version,
            subject_id=run.subject_id,
            aggregate_score=run.aggregate_score,
            evaluation_id=run.evaluation_id,
            created_at=utc_now(),
        )
        target = self.runs_dir / run.evaluation_id / "baseline.json"
        target.write_text(json.dumps(baseline.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return baseline

    def _persist(self, run: EvaluationRun, suite: BenchmarkSuite) -> None:
        target = self.runs_dir / run.evaluation_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "suite.json").write_text(
            json.dumps(suite.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (target / "evaluation.json").write_text(
            json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


def compare_evaluations(
    baseline: EvaluationRun,
    candidate: EvaluationRun,
    *,
    critical_case_ids: set[str] | None = None,
    epsilon: float = 1e-9,
) -> EvaluationComparison:
    if (baseline.suite_id, baseline.suite_version) != (candidate.suite_id, candidate.suite_version):
        return EvaluationComparison(
            baseline_evaluation_id=baseline.evaluation_id,
            candidate_evaluation_id=candidate.evaluation_id,
            baseline_score=baseline.aggregate_score,
            candidate_score=candidate.aggregate_score,
            absolute_delta=0.0,
            percent_delta=None,
            improved_cases=(),
            degraded_cases=(),
            critical_regressions=(),
            decision="invalid",
        )

    baseline_map = {item.case_id: item for item in baseline.results}
    candidate_map = {item.case_id: item for item in candidate.results}
    if baseline_map.keys() != candidate_map.keys():
        return EvaluationComparison(
            baseline_evaluation_id=baseline.evaluation_id,
            candidate_evaluation_id=candidate.evaluation_id,
            baseline_score=baseline.aggregate_score,
            candidate_score=candidate.aggregate_score,
            absolute_delta=0.0,
            percent_delta=None,
            improved_cases=(),
            degraded_cases=(),
            critical_regressions=(),
            decision="invalid",
        )

    improved: list[str] = []
    degraded: list[str] = []
    for case_id in sorted(baseline_map):
        delta = candidate_map[case_id].score - baseline_map[case_id].score
        if delta > epsilon:
            improved.append(case_id)
        elif delta < -epsilon:
            degraded.append(case_id)

    critical = tuple(sorted(set(degraded) & set(critical_case_ids or set())))
    absolute_delta = round(candidate.aggregate_score - baseline.aggregate_score, 6)
    percent_delta = None if baseline.aggregate_score == 0 else round(
        (absolute_delta / baseline.aggregate_score) * 100.0, 6
    )
    if critical or absolute_delta < -epsilon:
        decision = "regressed"
    elif absolute_delta > epsilon and not degraded:
        decision = "improved"
    else:
        decision = "neutral"

    return EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=baseline.aggregate_score,
        candidate_score=candidate.aggregate_score,
        absolute_delta=absolute_delta,
        percent_delta=percent_delta,
        improved_cases=tuple(improved),
        degraded_cases=tuple(degraded),
        critical_regressions=critical,
        decision=decision,
    )
