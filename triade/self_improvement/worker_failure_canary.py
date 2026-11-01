"""Canary en sombra: nunca confunde clasificación con reparación causal."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from triade.db import sqlite3

from .worker_failure_ab import (
    WorkerFailureABRunner,
    _variant_reject_requested,
    _variant_strict_terminal,
)

_CANARY_MIN_POSITIVE = 3
_CANARY_MIN_NEGATIVE = 2
_CANARY_LIMIT = 60
_VARIANTS = {
    "B1-explicit-cancellation": _variant_reject_requested,
    "B2-strict-terminal": _variant_strict_terminal,
}


class WorkerFailureShadowCanary:
    """Mide contra incidentes POSTERIORES a la evaluación offline."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _experiment(self) -> dict[str, Any] | None:
        with sqlite3.connect(
            self.db_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as conn:
            names = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "failure_ab_experiments" not in names:
                return None
            row = conn.execute(
                "SELECT experiment_id,result_json,created_at "
                "FROM failure_ab_experiments ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            if "failure_ab_shadow_canaries" in names:
                past = conn.execute(
                    "SELECT 1 FROM failure_ab_shadow_canaries WHERE experiment_id=?",
                    (row[0],),
                ).fetchone()
                if past:
                    return None
        try:
            result = json.loads(row[1])
        except (ValueError, TypeError):
            return None
        if (
            not isinstance(result, dict)
            or not result.get("eligible_for_canary")
            or result.get("winner") not in _VARIANTS
            or result.get("causal_attribution") != "paired_offline_replay_only"
        ):
            return None
        return {
            "experiment_id": str(row[0]),
            "created_at": str(row[2]),
            "result": result,
        }

    @staticmethod
    def _used_case_ids(result: Mapping[str, Any]) -> set[str]:
        used = {
            str(item["case_id"])
            for item in result.get("train_baseline_observations", ())
            if isinstance(item, dict) and item.get("case_id")
        }
        for name in ("holdout_observations", "negative_observations"):
            arms = result.get(name) or {}
            if isinstance(arms, dict):
                for arm in ("A", "B"):
                    used.update(
                        str(item["case_id"])
                        for item in arms.get(arm, ())
                        if isinstance(item, dict) and item.get("case_id")
                    )
        return used

    def _recent_cases(self, experiment: dict[str, Any]) -> list[dict[str, Any]]:
        observations = WorkerFailureABRunner(self.db_path)._load_observations()
        used = self._used_case_ids(experiment["result"])
        with sqlite3.connect(
            self.db_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as conn:
            names = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            eligible: set[str] = set()
            sources = (
                ("worker-event", "worker_events", "id"),
                (
                    "autonomous-transition",
                    "autonomous_task_transitions",
                    "transition_id",
                ),
            )
            for prefix, table, identity in sources:
                if table not in names:
                    continue
                columns = {
                    str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")
                }
                if "created_at" not in columns:
                    continue
                for row in conn.execute(
                    f"SELECT {identity},created_at FROM {table} "
                    "WHERE julianday(created_at) > julianday(?) "
                    "ORDER BY created_at ASC LIMIT ?",
                    (experiment["created_at"], _CANARY_LIMIT),
                ):
                    eligible.add(f"{prefix}:{row[0]}")
        return [
            item
            for item in observations
            if item["source_ref"] in eligible and f"task-{item['task_id']}" not in used
        ]

    def ready(self) -> bool:
        experiment = self._experiment()
        if not experiment:
            return False
        cases = self._recent_cases(experiment)
        return (
            sum(item["expected"] is True for item in cases) >= _CANARY_MIN_POSITIVE
            and sum(item["expected"] is False for item in cases) >= _CANARY_MIN_NEGATIVE
        )

    def observe(self) -> dict[str, Any]:
        experiment = self._experiment()
        if experiment is None:
            return {
                "status": "no_evidence",
                "reason": "no_eligible_unobserved_experiment",
                "operational_causality_proven": False,
            }
        observations = self._recent_cases(experiment)
        positive = [x for x in observations if x["expected"] is True][
            :_CANARY_MIN_POSITIVE
        ]
        negative = [x for x in observations if x["expected"] is False][
            :_CANARY_MIN_NEGATIVE
        ]
        if len(positive) < _CANARY_MIN_POSITIVE or len(negative) < _CANARY_MIN_NEGATIVE:
            return {
                "status": "no_evidence",
                "reason": "insufficient_new_verified_canary_outcomes",
                "operational_causality_proven": False,
            }
        from triade.workers.worker_loop import _should_learn_from_worker_outcome

        winner = str(experiment["result"]["winner"])
        variant = _VARIANTS[winner]
        cases = positive + negative
        results = []
        for item in cases:
            inputs = {
                "status": item["status"],
                "reason": item["payload"].get("reason"),
                "error": item["payload"].get("error"),
                "message": item["payload"].get("message"),
                "skipped_reason": item["payload"].get("skipped_reason"),
            }
            baseline = _should_learn_from_worker_outcome(item["status"], dict(inputs))
            candidate = bool(variant(inputs))
            results.append(
                {
                    "case_id": f"task-{item['task_id']}",
                    "evidence_ref": item["source_ref"],
                    "expected": item["expected"],
                    "baseline_correct": baseline == item["expected"],
                    "candidate_correct": candidate == item["expected"],
                    "safety_control": item["expected"] is False,
                }
            )
        passed = all(x["candidate_correct"] for x in results) and sum(
            x["candidate_correct"] for x in results
        ) >= sum(x["baseline_correct"] for x in results)
        report = {
            "status": "completed",
            "experiment_id": experiment["experiment_id"],
            "winner": winner,
            "shadow_verdict": "supported" if passed else "regressed",
            "evaluated_cases": len(results),
            "observations": results,
            "case_refs_hash": hashlib.sha256(
                json.dumps(sorted(x["evidence_ref"] for x in results)).encode()
            ).hexdigest(),
            "operational_causality_proven": False,
            "production_effect_applied": False,
            "stable_memory_written": False,
            "rollback_required": False,
        }
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS failure_ab_shadow_canaries ("
                "experiment_id TEXT PRIMARY KEY, result_json TEXT NOT NULL, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "INSERT OR IGNORE INTO failure_ab_shadow_canaries "
                "(experiment_id,result_json) VALUES (?,?)",
                (experiment["experiment_id"], json.dumps(report, sort_keys=True)),
            )
            saved = conn.execute(
                "SELECT result_json FROM failure_ab_shadow_canaries "
                "WHERE experiment_id=?",
                (experiment["experiment_id"],),
            ).fetchone()
        return json.loads(saved[0])
