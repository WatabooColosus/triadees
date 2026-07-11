from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.core.observability_view import TriadeObservabilityView
from triade.evaluation import EvaluationRun, MetricResult
from triade.regression import MetricPolicy, RegressionGate
from triade.regression.observability import RegressionObservability


def make_run(evaluation_id: str, score: float) -> EvaluationRun:
    return EvaluationRun(
        evaluation_id=evaluation_id,
        suite_id="critical",
        suite_version="1.0.0",
        subject_id=evaluation_id,
        results=(
            MetricResult(
                case_id="identity_core",
                score=score,
                passed=score >= 0.5,
                actual=score,
                expected=1.0,
            ),
        ),
        aggregate_score=score,
        created_at="2026-07-11T00:00:00+00:00",
    )


def test_regression_snapshot_tolerates_existing_partial_database(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")

    snapshot = RegressionObservability(db_path).snapshot()

    assert snapshot["status"] == "not_initialized"
    assert snapshot["schema_ready"] is False
    assert snapshot["reports"]["total"] == 0


def test_unified_observability_exposes_regression_gate(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"

    payload = TriadeObservabilityView(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        worker_runs_dir=tmp_path / "background",
    ).build(limit=3)

    assert "regression_gate" in payload
    assert payload["regression_gate"]["status"] in {"healthy", "not_initialized"}
    assert "regression_gate" not in payload["degraded_sources"]


def test_unified_observability_degrades_on_active_regression_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "triade.db"
    gate = RegressionGate(db_path)
    baseline = make_run("baseline", 1.0)
    candidate = make_run("candidate", 0.7)
    gate.record_stable_state("learning", baseline)
    gate.evaluate(
        report_id="report-fail",
        candidate_id="candidate-fail",
        capability="learning",
        baseline=baseline,
        candidate=candidate,
        policies=(MetricPolicy("identity_core", severity="critical"),),
    )

    payload = TriadeObservabilityView(
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        worker_runs_dir=tmp_path / "background",
    ).build(limit=3)

    assert payload["regression_gate"]["status"] == "attention"
    assert payload["regression_gate"]["quarantine"]["active"] == 1
    assert payload["status"] == "degraded"
    assert any("Regression Gate requiere atención" in item for item in payload["warnings"])
