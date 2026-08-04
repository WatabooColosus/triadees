from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult
from triade.learning.context_selection_benchmark import (
    CAPABILITY,
    load_benchmark,
    run_phase_1_experiment,
)
from triade.learning.pipeline import LearningPipeline

BENCHMARK_DIR = (
    Path(__file__).resolve().parents[1] / "benchmarks/learning/context_selection/v1"
)


def _run(
    evaluation_id: str,
    subject_id: str,
    *,
    train: float,
    validation: float,
    held_out: float,
    regression: float,
) -> EvaluationRun:
    score = (train + validation + held_out + regression) / 4
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id="phase-1-gate",
        suite_version="1.0.0",
        subject_id=subject_id,
        results=(MetricResult("aggregate", score, score == 1.0, score, 1.0),),
        aggregate_score=score,
        created_at="2026-08-03T00:00:00Z",
        metadata={
            "split_scores": {
                "train": train,
                "validation": validation,
                "held_out": held_out,
                "regression": regression,
            }
        },
    )


def _comparison(
    baseline: EvaluationRun, candidate: EvaluationRun
) -> EvaluationComparison:
    return EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=baseline.aggregate_score,
        candidate_score=candidate.aggregate_score,
        absolute_delta=candidate.aggregate_score - baseline.aggregate_score,
        percent_delta=None,
        improved_cases=("aggregate",),
        degraded_cases=(),
        critical_regressions=(),
        decision="improved",
    )


def _measurable_candidate(pipe: LearningPipeline, suffix: str) -> str:
    candidate = pipe.ingest(
        content=f"Contexto medible para recuperación SQLite con rollback {suffix}",
        source_type="repo",
        source_ref=f"pytest:{suffix}",
        title=f"Contexto {suffix}",
        domain=CAPABILITY,
    )
    candidate_id = str(candidate["candidate_id"])
    pipe.evaluate(candidate_id)
    pipe.verify(candidate_id)
    return candidate_id


def test_benchmark_is_versioned_and_contains_every_required_split() -> None:
    loaded = load_benchmark(BENCHMARK_DIR)
    assert loaded.suite.version == "1.0.0"
    assert set(loaded.split_by_case.values()) == {
        "train",
        "validation",
        "held_out",
        "adversarial",
        "regression",
    }


def test_candidate_without_measurement_evidence_does_not_consolidate(
    tmp_path: Path,
) -> None:
    pipe = LearningPipeline(tmp_path / "phase1.db", enforce_model_policy=False)
    candidate_id = _measurable_candidate(pipe, "without-evidence")
    with sqlite3.connect(pipe.db_path) as conn:
        conn.execute(
            "UPDATE learning_queue SET run_use_count=3, run_outcome_scores='[1,1,1]', "
            "avg_outcome_score=1.0 WHERE candidate_id=?",
            (candidate_id,),
        )
    with pytest.raises(ValueError, match="No existe evidencia Measurement Core"):
        pipe.consolidate(
            candidate_id, approved_by="phase-1-test", auto_consolidate=False
        )


def test_candidate_improving_only_train_does_not_consolidate(tmp_path: Path) -> None:
    pipe = LearningPipeline(tmp_path / "phase1.db", enforce_model_policy=False)
    candidate_id = _measurable_candidate(pipe, "train-only")
    baseline = _run(
        "baseline-train-only",
        "phase-1-train-only",
        train=0.0,
        validation=1.0,
        held_out=1.0,
        regression=1.0,
    )
    candidate = _run(
        "candidate-train-only",
        "phase-1-train-only",
        train=1.0,
        validation=1.0,
        held_out=1.0,
        regression=1.0,
    )
    pipe.evidence_bridge.declare_hypothesis(
        candidate_id,
        hypothesis="Mejora solo train debe quedar bloqueada.",
        capability=CAPABILITY,
        subject_id="phase-1-train-only",
        require_generalization=True,
    )
    pipe.evidence_bridge.record_comparison(
        candidate_id,
        baseline=baseline,
        candidate=candidate,
        comparison=_comparison(baseline, candidate),
    )
    for index in range(2):
        pipe.mark_used_in_run(candidate_id, f"train-only-{index}", 1.0)
    with pytest.raises(ValueError, match="limitada a train"):
        pipe.mark_used_in_run(candidate_id, "train-only-2", 1.0)
    assert pipe.get_candidate(candidate_id)["status"] == "internally_checked"


def test_candidate_with_critical_regression_does_not_advance(tmp_path: Path) -> None:
    pipe = LearningPipeline(tmp_path / "phase1.db", enforce_model_policy=False)
    candidate_id = _measurable_candidate(pipe, "critical-regression")
    baseline = _run(
        "baseline-regression",
        "phase-1-regression",
        train=0.0,
        validation=0.0,
        held_out=1.0,
        regression=1.0,
    )
    candidate = _run(
        "candidate-regression",
        "phase-1-regression",
        train=1.0,
        validation=1.0,
        held_out=1.0,
        regression=0.0,
    )
    comparison = EvaluationComparison(
        baseline_evaluation_id=baseline.evaluation_id,
        candidate_evaluation_id=candidate.evaluation_id,
        baseline_score=baseline.aggregate_score,
        candidate_score=candidate.aggregate_score,
        absolute_delta=candidate.aggregate_score - baseline.aggregate_score,
        percent_delta=None,
        improved_cases=("aggregate",),
        degraded_cases=("regression",),
        critical_regressions=("regression",),
        decision="regressed",
    )
    pipe.evidence_bridge.declare_hypothesis(
        candidate_id,
        hypothesis="Una regresión crítica debe bloquear.",
        capability=CAPABILITY,
        subject_id="phase-1-regression",
    )
    pipe.evidence_bridge.record_comparison(
        candidate_id,
        baseline=baseline,
        candidate=candidate,
        comparison=comparison,
    )
    with pytest.raises(ValueError, match="no demuestra mejora"):
        pipe.evidence_bridge.require_improvement(candidate_id)


def test_non_measurable_candidate_is_explicitly_marked(tmp_path: Path) -> None:
    pipe = LearningPipeline(tmp_path / "phase1.db", enforce_model_policy=False)
    candidate_id = _measurable_candidate(pipe, "not-measurable")
    evidence = pipe.evidence_bridge.record_inconclusive(
        candidate_id,
        decision="not_measurable",
        reason="no existe expected_output verificable",
        capability=CAPABILITY,
    )
    assert evidence["decision"] == "not_measurable"
    with pytest.raises(ValueError, match="not_measurable"):
        pipe.evidence_bridge.require_improvement(candidate_id)


def test_real_learning_cycle_improves_generalizes_consolidates_and_reuses(
    tmp_path: Path,
) -> None:
    result = run_phase_1_experiment(
        BENCHMARK_DIR,
        work_dir=tmp_path / "experiment",
        sha="09b0248038cd4a2689355610cf823683a8a869e2",
    )

    assert result["comparison"]["decision"] == "improved"
    assert (
        result["baseline"]["aggregate_score"] < result["treatment"]["aggregate_score"]
    )
    assert result["regression_gate"]["decision"] == "pass"
    assert result["candidate"]["status"] == "consolidated"
    assert result["followup"]["decision_changed"] is True
    assert result["followup"]["causal_use_confirmed"] is True
    assert result["followup"]["audit_row_id"] > 0
    assert all(result["closure"].values())

    repeated = run_phase_1_experiment(
        BENCHMARK_DIR,
        work_dir=tmp_path / "reproduction",
        sha="09b0248038cd4a2689355610cf823683a8a869e2",
    )
    assert (
        repeated["baseline"]["aggregate_score"] == result["baseline"]["aggregate_score"]
    )
    assert (
        repeated["treatment"]["aggregate_score"]
        == result["treatment"]["aggregate_score"]
    )
    assert repeated["closure"] == result["closure"]


def test_phase_1_cli_is_isolated_and_reproducible_by_default(tmp_path: Path) -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts/run_phase_1_learning_end_to_end.py"
    )
    outputs = [tmp_path / "first.json", tmp_path / "second.json"]

    for output in outputs:
        completed = subprocess.run(
            [sys.executable, str(script), "--output", str(output)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr

    first, second = (json.loads(path.read_text(encoding="utf-8")) for path in outputs)
    assert first["baseline"]["aggregate_score"] == second["baseline"]["aggregate_score"]
    assert (
        first["treatment"]["aggregate_score"] == second["treatment"]["aggregate_score"]
    )
    assert first["closure"] == second["closure"]
