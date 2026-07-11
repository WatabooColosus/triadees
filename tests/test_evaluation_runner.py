from __future__ import annotations

import json

from triade.evaluation import BenchmarkCase, BenchmarkSuite, EvaluationRunner, compare_evaluations
from triade.evaluation.suites import core_safety_suite, evaluate_core_safety_case


def test_runner_persists_weighted_evaluation_and_baseline(tmp_path) -> None:
    runner = EvaluationRunner(tmp_path / "evaluations")
    suite = BenchmarkSuite(
        suite_id="weighted",
        version="1.0.0",
        capability="weighted_scoring",
        cases=(
            BenchmarkCase("case-a", "weighted_scoring", {}, True, weight=3.0),
            BenchmarkCase("case-b", "weighted_scoring", {}, False, weight=1.0),
        ),
    )

    run = runner.run(suite, subject_id="subject-v1", evaluator=lambda case: case.case_id == "case-a")
    baseline = runner.create_baseline(suite.capability, run)

    assert run.aggregate_score == 1.0
    run_dir = tmp_path / "evaluations" / run.evaluation_id
    assert json.loads((run_dir / "evaluation.json").read_text())["aggregate_score"] == 1.0
    assert json.loads((run_dir / "suite.json").read_text())["suite_id"] == "weighted"
    assert json.loads((run_dir / "baseline.json").read_text())["baseline_id"] == baseline.baseline_id


def test_core_safety_suite_executes_without_external_dependencies(tmp_path) -> None:
    runner = EvaluationRunner(tmp_path / "evaluations")
    suite = core_safety_suite()

    run = runner.run(suite, subject_id="triade-main", evaluator=evaluate_core_safety_case)

    assert run.aggregate_score == 1.0
    assert all(result.passed for result in run.results)
    assert len(run.results) == 5


def test_comparison_detects_improvement_and_critical_regression(tmp_path) -> None:
    runner = EvaluationRunner(tmp_path / "evaluations")
    suite = BenchmarkSuite(
        suite_id="compare",
        version="1.0.0",
        capability="comparison",
        cases=(
            BenchmarkCase("critical", "comparison", {}, True, critical=True),
            BenchmarkCase("normal", "comparison", {}, True),
        ),
    )
    baseline = runner.run(suite, subject_id="base", evaluator=lambda _case: False)
    improved = runner.run(suite, subject_id="candidate", evaluator=lambda _case: True)
    regressed = runner.run(
        suite,
        subject_id="candidate-bad",
        evaluator=lambda case: case.case_id != "critical",
    )

    good = compare_evaluations(baseline, improved, critical_case_ids={"critical"})
    bad = compare_evaluations(improved, regressed, critical_case_ids={"critical"})

    assert good.decision == "improved"
    assert good.improved_cases == ("critical", "normal")
    assert bad.decision == "regressed"
    assert bad.critical_regressions == ("critical",)


def test_comparison_rejects_different_suite_versions(tmp_path) -> None:
    runner = EvaluationRunner(tmp_path / "evaluations")
    suite_v1 = BenchmarkSuite(
        suite_id="suite",
        version="1.0.0",
        capability="cap",
        cases=(BenchmarkCase("case", "cap", {}, True),),
    )
    suite_v2 = BenchmarkSuite(
        suite_id="suite",
        version="2.0.0",
        capability="cap",
        cases=(BenchmarkCase("case", "cap", {}, True),),
    )
    first = runner.run(suite_v1, subject_id="one", evaluator=lambda _case: True)
    second = runner.run(suite_v2, subject_id="two", evaluator=lambda _case: True)

    assert compare_evaluations(first, second).decision == "invalid"
