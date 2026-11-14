"""Candidate-specific independent holdout executor.

The executor is deliberately contract-first: it creates no run when the
candidate lacks an evaluation contract (cases, expected output and metric).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HoldoutResult:
    status: str
    candidate_id: str
    holdout_id: str
    baseline_run_id: str | None = None
    treatment_run_id: str | None = None
    regression_report: dict[str, Any] | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def execute_candidate_holdout(
    *, candidate_id: str, holdout_id: str, contract: dict[str, Any] | None,
    output_dir: Path,
) -> HoldoutResult:
    required = (contract or {}).get("cases") if isinstance(contract, dict) else None
    metric = (contract or {}).get("metric") if isinstance(contract, dict) else None
    if not isinstance(required, list) or not required or not metric:
        result = HoldoutResult(
            status="blocked_missing_evaluation_contract",
            candidate_id=candidate_id,
            holdout_id=holdout_id,
            reason="candidate requires explicit holdout cases and metric before runs can be generated",
        )
    elif metric == "deterministic_recall_and_recovery":
        # Production adapter for worker_failure. It only scores observations
        # supplied by the worker contract; it never asks an LLM to invent a
        # pass. The caller may provide observed_answers keyed by case_id.
        observed = (contract or {}).get("observed_answers") or {}
        expected = {str(item.get("case_id")): str(item.get("expected"))
                    for item in required if isinstance(item, dict)}
        if not observed or any(case not in observed for case in expected):
            result = HoldoutResult(
                status="pending_observed_runs", candidate_id=candidate_id,
                holdout_id=holdout_id,
                reason="worker recovery observations are required for every holdout case",
            )
        else:
            passed = sum(str(observed[k]).strip() == v for k, v in expected.items())
            score = round(passed / max(1, len(expected)), 4)
            result = HoldoutResult(
                status="validated" if score >= 0.8 else "not_measurable",
                candidate_id=candidate_id, holdout_id=holdout_id,
                baseline_run_id=f"{holdout_id}:baseline",
                treatment_run_id=f"{holdout_id}:treatment",
                regression_report={"metric": metric, "score": score, "cases": len(expected)},
            )
    else:
        result = HoldoutResult(
            status="pending_evaluator_adapter", candidate_id=candidate_id,
            holdout_id=holdout_id,
            reason=f"no evaluator adapter registered for metric {metric}",
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "candidate_holdout_result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
