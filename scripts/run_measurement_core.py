"""Ejecuta la baseline local de Measurement Core y emite evidencia auditable."""

from __future__ import annotations

import json
from pathlib import Path

from triade.evaluation import EvaluationRunner
from triade.evaluation.suites import core_safety_suite, evaluate_core_safety_case


def main() -> int:
    runner = EvaluationRunner(Path("runs/evaluations"))
    suite = core_safety_suite()
    run = runner.run(
        suite,
        subject_id="triade-core-current",
        evaluator=evaluate_core_safety_case,
        metadata={"mode": "deterministic_local", "network": False, "shell": False},
    )
    baseline = runner.create_baseline(suite.capability, run)
    summary = {
        "status": "passed" if run.aggregate_score == 1.0 else "failed",
        "evaluation_id": run.evaluation_id,
        "baseline_id": baseline.baseline_id,
        "suite_id": suite.suite_id,
        "suite_version": suite.version,
        "aggregate_score": run.aggregate_score,
        "cases": len(run.results),
        "artifact_dir": str(Path("runs/evaluations") / run.evaluation_id),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
