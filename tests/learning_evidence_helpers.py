from __future__ import annotations

from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.pipeline import LearningPipeline


def attach_improved_evidence(
    pipe: LearningPipeline,
    candidate_id: str,
    *,
    capability: str = "test_learning_capability",
    suite_id: str = "test-learning-suite",
    case_id: str = "test-learning-case",
) -> None:
    subject = f"candidate:{candidate_id}"
    pipe.evidence_bridge.declare_hypothesis(
        candidate_id,
        hypothesis="El candidato mejora una capacidad medible durante pruebas.",
        capability=capability,
        subject_id=subject,
    )
    baseline = EvaluationRun(
        evaluation_id=f"base-{candidate_id}",
        suite_id=suite_id,
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult(case_id, 0.0, False, False, True),),
        aggregate_score=0.0,
        created_at="2026-07-11T00:00:00Z",
    )
    candidate = EvaluationRun(
        evaluation_id=f"candidate-{candidate_id}",
        suite_id=suite_id,
        suite_version="1.0.0",
        subject_id=subject,
        results=(MetricResult(case_id, 1.0, True, True, True),),
        aggregate_score=1.0,
        created_at="2026-07-11T00:00:01Z",
    )
    comparison = EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=0.0,
        candidate_score=1.0,
        absolute_delta=1.0,
        percent_delta=None,
        improved_cases=(case_id,),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )
    pipe.evidence_bridge.record_comparison(
        candidate_id,
        baseline=baseline,
        candidate=candidate,
        comparison=comparison,
        artifact_ref=f"runs/learning_evidence/{candidate_id}",
    )
