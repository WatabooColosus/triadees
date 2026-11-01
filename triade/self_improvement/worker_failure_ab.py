"""Reproducción autónoma A/B de clasificación de fallos de workers.

SÓLO usa resultados de tareas y eventos terminales relacionados por run/task id.
No crea fallos, no repite prompts, no escribe memoria estable y no cambia
la política del worker vivo. Los casos sin procedencia concordante se descartan.

Esto compara políticas de clasificación de incidentes, NO demuestra por sí
solo que una reparación funcional de una tarea arregle su causa de origen.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.runtime.task_status import TERMINAL_FAILURE

from .failure_ab import CandidateVariant, FailureABGate, FailureCase

_FAILURE_METRIC = "worker_outcome_classification"
_SUPPORTED_STATUSES = frozenset(
    {
        "completed",
        "observed",
        "cancelled",
        "failed",
        "dead_letter",
        "timeout",
        "lease_lost",
        "blocked",
    }
)
_SOURCE_EVENT_LIMIT = 300
_MIN_CASES = 11


def _explicit_cancellation(payload: Mapping[str, Any]) -> bool:
    return any(
        str(payload.get(key) or "").strip().casefold() == "cancellation_requested"
        for key in ("reason", "error", "message", "skipped_reason")
    )


def _classification_label(status: str, payload: dict[str, Any]) -> bool:
    """Oráculo de etiqueta basado en TERMINAL_FAILURE y cancelación explícita.

    No hay afirmación de que el worker haya *mejorado*: sólo clasifica
    si un incidente merece entrar al circuito de investigación.
    """
    if _explicit_cancellation(payload):
        return False
    return status in TERMINAL_FAILURE or status in {"blocked", "cancelled"}


def _variant_reject_requested(payload: Mapping[str, Any]) -> bool:
    status = str(payload["status"])
    if _explicit_cancellation(payload):
        return False
    return status in TERMINAL_FAILURE or status in {"blocked", "cancelled"}


def _variant_strict_terminal(payload: Mapping[str, Any]) -> bool:
    status = str(payload["status"])
    if _explicit_cancellation(payload):
        return False
    return status in TERMINAL_FAILURE


class WorkerFailureABRunner:
    """Lee eventos reales, compara variantes confiables y devuelve un dict."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _load_observations(self) -> list[dict[str, Any]]:
        with sqlite3.connect(
            self.db_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as conn:
            conn.row_factory = sqlite3.Row
            names = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            rows = (
                conn.execute(
                    """SELECT e.id AS event_id,e.task_id,e.task_type,
                          e.run_ref AS event_run,e.event_type,
                          e.payload_json AS event_payload,
                          t.status AS task_status,t.result_json AS task_result,
                          t.run_ref AS task_run,t.task_type AS recorded_task_type
                   FROM worker_events e
                   JOIN worker_tasks t ON t.id=e.task_id
                   WHERE e.event_type LIKE 'task_%'
                   ORDER BY e.id DESC LIMIT ?""",
                    (_SOURCE_EVENT_LIMIT,),
                ).fetchall()
                if {"worker_events", "worker_tasks"} <= names
                else []
            )
        observations = []
        seen_tasks: set[int] = set()
        for row in rows:
            try:
                task_id = int(row["task_id"])
                status = str(row["task_status"] or "")
                payload = json.loads(row["event_payload"] or "{}")
                task_result = json.loads(row["task_result"] or "{}")
            except (ValueError, TypeError, KeyError):
                continue
            if (
                task_id in seen_tasks
                or status not in _SUPPORTED_STATUSES
                or not isinstance(payload, dict)
                or not isinstance(task_result, dict)
                or payload != task_result
                or row["event_type"] != "task_" + status
                or not row["event_run"]
                or row["event_run"] != row["task_run"]
                or not row["task_type"]
                or row["task_type"] != row["recorded_task_type"]
            ):
                continue
            seen_tasks.add(task_id)
            observations.append(
                {
                    "event_id": int(row["event_id"]),
                    "task_id": task_id,
                    "status": status,
                    "payload": payload,
                    "expected": _classification_label(status, payload),
                    "source_ref": f"worker-event:{row['event_id']}",
                }
            )
        observations.extend(self._load_v2_observations())
        return sorted(observations, key=lambda x: str(x["source_ref"]))

    def _load_v2_observations(self) -> list[dict[str, Any]]:
        """Solo estados terminales con transición y artefacto canónico íntegro."""
        with sqlite3.connect(
            self.db_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as conn:
            conn.row_factory = sqlite3.Row
            names = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {"autonomous_tasks", "autonomous_task_transitions"} <= names:
                return []
            rows = conn.execute(
                """SELECT t.task_id,t.task_type,t.status,t.worker_id,
                          t.result_ref,t.lease_generation,
                          e.transition_id,e.to_status,e.result_ref AS event_ref,
                          e.worker_id AS event_worker,
                          e.lease_generation AS event_generation
                   FROM autonomous_task_transitions e
                   JOIN autonomous_tasks t ON t.task_id=e.task_id
                   WHERE e.to_status IN
                   ('completed','observed','cancelled','blocked',
                    'failed','dead_letter','timeout','lease_lost')
                   ORDER BY e.transition_id DESC LIMIT ?""",
                (_SOURCE_EVENT_LIMIT,),
            ).fetchall()
        observations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            task_id = str(row["task_id"] or "")
            status = str(row["status"] or "")
            reference = str(row["result_ref"] or "")
            if (
                not task_id
                or task_id in seen
                or status not in _SUPPORTED_STATUSES
                or row["to_status"] != status
                or not reference
                or reference != row["event_ref"]
                or row["worker_id"] != row["event_worker"]
                or row["lease_generation"] != row["event_generation"]
            ):
                continue
            artifact = Path(reference)
            manifest_file = artifact.parent / "manifest.json"
            try:
                if (
                    artifact.name != "result.json"
                    or artifact.is_symlink()
                    or artifact.parent.is_symlink()
                    or not artifact.is_file()
                    or not manifest_file.is_file()
                    or artifact.stat().st_size > 131072
                    or manifest_file.stat().st_size > 131072
                ):
                    continue
                raw_result = artifact.read_bytes()
                manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                payload = json.loads(raw_result)
            except (OSError, ValueError, TypeError):
                continue
            digest = hashlib.sha256(raw_result).hexdigest()
            if (
                not isinstance(payload, dict)
                or not isinstance(manifest, dict)
                or manifest.get("task_id") != task_id
                or manifest.get("task_type") != row["task_type"]
                or manifest.get("worker_id") != row["worker_id"]
                or manifest.get("status") != status
                or manifest.get("lease_generation") != row["lease_generation"]
                or manifest.get("result_hash") != digest
                or not isinstance(manifest.get("artifact_hashes"), dict)
                or manifest["artifact_hashes"].get("result.json") != digest
            ):
                continue
            seen.add(task_id)
            observations.append(
                {
                    "event_id": int(row["transition_id"]),
                    "task_id": "v2-" + task_id,
                    "status": status,
                    "payload": payload,
                    "expected": _classification_label(status, payload),
                    "source_ref": f"autonomous-transition:{row['transition_id']}",
                }
            )
        return observations

    def replay_cases(self) -> list[FailureCase]:
        """Partición por tarea real, sin duplicar el mismo evento.

        Se reservan controles negativos reales (cancelaciones solicitadas,
        tareas completadas u observadas), y el resto se reparte en entrenamiento
        y holdout. Si no existen suficientes observaciones, no se ensaya.
        """
        observations = self._load_observations()
        negatives = [x for x in observations if x["expected"] is False]
        positives = [x for x in observations if x["expected"] is True]
        if len(negatives) < 5 or len(positives) < 6:
            return []
        chosen = {
            "negative": negatives[3:5],
            "train": positives[:3] + negatives[:2],
            "holdout": positives[3:6] + negatives[2:3],
        }
        cases: list[FailureCase] = []
        for split, rows in chosen.items():
            for observation in rows:
                payload = observation["payload"]
                cases.append(
                    FailureCase(
                        case_id=f"task-{observation['task_id']}",
                        split=split,
                        inputs={
                            "status": observation["status"],
                            "reason": payload.get("reason"),
                            "error": payload.get("error"),
                            "message": payload.get("message"),
                            "skipped_reason": payload.get("skipped_reason"),
                        },
                        expected=observation["expected"],
                        evidence_ref=str(observation["source_ref"]),
                        safety_critical=(split == "negative"),
                    )
                )
        return cases

    def _cohort_identity(self, cases: list[FailureCase]) -> str:
        refs = sorted(c.evidence_ref for c in cases)
        return hashlib.sha256(
            json.dumps(refs, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]

    def pending_auto_measurement(self) -> bool:
        """Una regresión observada, no un prompt ni un contador arbitrario."""
        cases = self.replay_cases()
        if len(cases) < _MIN_CASES:
            return False
        from triade.workers.worker_loop import _should_learn_from_worker_outcome

        mismatches = {
            split: sum(
                _should_learn_from_worker_outcome(
                    str(case.inputs["status"]), dict(case.inputs)
                )
                != case.expected
                for case in cases
                if case.split == split
            )
            for split in ("train", "holdout")
        }
        if not (mismatches["train"] and mismatches["holdout"]):
            return False
        report_id = "worker-ab-regression-" + self._cohort_identity(cases)
        with sqlite3.connect(
            self.db_path.resolve().as_uri() + "?mode=ro", uri=True
        ) as conn:
            tables = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "regression_reports" in tables:
                attempts = conn.execute(
                    "SELECT COUNT(*) FROM regression_reports "
                    "WHERE suite_id='worker-outcome-classification'"
                ).fetchone()[0] if "suite_id" in {
                    str(c[1])
                    for c in conn.execute("PRAGMA table_info(regression_reports)")
                } else 0
                if attempts >= 5:
                    return False
            if "failure_ab_experiments" in tables:
                for row in conn.execute(
                    "SELECT report_id,result_json FROM failure_ab_experiments"
                ):
                    if row[0] == report_id:
                        return False
                    try:
                        result = json.loads(row[1])
                    except (ValueError, TypeError):
                        return False
                    used = {
                        str(item.get("case_id"))
                        for item in result.get("train_baseline_observations", [])
                        if isinstance(item, dict)
                    }
                    for split in ("holdout_observations", "negative_observations"):
                        observations = result.get(split) or {}
                        if isinstance(observations, dict):
                            used.update(
                                str(item.get("case_id"))
                                for arm in ("A", "B")
                                for item in observations.get(arm, [])
                                if isinstance(item, dict)
                            )
                    if any(case.case_id in used for case in cases):
                        return False
        return True

    def evaluate_auto(self) -> dict[str, Any]:
        """Regresión real desde tareas archivadas; luego comparación A/B."""
        cases = self.replay_cases()
        if not self.pending_auto_measurement():
            return {
                "status": "no_evidence",
                "reason": "no_measured_worker_regression_or_attempts_exhausted",
                "stable_memory_written": False,
            }
        from triade.evaluation import EvaluationRun, MetricResult
        from triade.regression import MetricPolicy, RegressionGate
        from triade.workers.worker_loop import _should_learn_from_worker_outcome

        cohort_id = self._cohort_identity(cases)
        report_id = "worker-ab-regression-" + cohort_id
        correct = sum(
            _should_learn_from_worker_outcome(
                str(case.inputs["status"]), dict(case.inputs)
            )
            == case.expected
            for case in cases
        )
        actual_score = correct / len(cases)
        now = datetime.now(UTC).isoformat()
        suite = "worker-outcome-classification"

        def measured(evaluation_id: str, score: float) -> EvaluationRun:
            return EvaluationRun(
                evaluation_id=evaluation_id,
                suite_id=suite,
                suite_version="failure-ab-1",
                subject_id=evaluation_id,
                results=(
                    MetricResult(
                        case_id=_FAILURE_METRIC,
                        score=score,
                        passed=score >= 1.0,
                        actual=score,
                        expected=1.0,
                    ),
                ),
                aggregate_score=score,
                created_at=now,
            )

        report = RegressionGate(self.db_path).evaluate(
            report_id=report_id,
            candidate_id="worker-outcome-policy-A-" + cohort_id,
            capability="worker_failure",
            baseline=measured(report_id + ":contract", 1.0),
            candidate=measured(report_id + ":runtime", actual_score),
            policies=(
                MetricPolicy(
                    metric_id=_FAILURE_METRIC,
                    severity="critical",
                    max_absolute_drop=0.0,
                    max_relative_drop=0.0,
                ),
            ),
            metadata={
                "evaluation_source": "canonical_worker_task_outcomes",
                "case_refs": [case.evidence_ref for case in cases],
                "cohort_id": cohort_id,
            },
        )
        if report.decision != "fail":
            return {
                "status": "no_evidence",
                "reason": "classification_did_not_regress",
                "stable_memory_written": False,
            }
        return self.evaluate(report_id, _FAILURE_METRIC)

    def evaluate(self, report_id: str, metric_id: str) -> dict[str, Any]:
        if metric_id != _FAILURE_METRIC:
            return {
                "status": "no_evidence",
                "reason": "unsupported_failure_metric",
                "stable_memory_written": False,
            }
        cases = self.replay_cases()
        if len(cases) < _MIN_CASES:
            return {
                "status": "no_evidence",
                "reason": "insufficient_distinct_worker_outcomes",
                "cases": len(cases),
                "stable_memory_written": False,
            }
        # El oráculo vuelve a leer los registros independientemente de las
        # funciones comparadas: un cambio en una variante no cambia la etiqueta.
        def oracle(case: FailureCase) -> bool:
            # Releer el estado real, sin confiar en callbacks de las variantes.
            current = self.replay_cases()
            verified = {str(x.evidence_ref): x for x in current}
            original = verified.get(case.evidence_ref)
            return bool(
                original is not None
                and original.case_id == case.case_id
                and original.expected is case.expected
                and dict(original.inputs) == dict(case.inputs)
            )

        from triade.workers.worker_loop import _should_learn_from_worker_outcome

        def baseline(inputs: Mapping[str, Any]) -> bool:
            return _should_learn_from_worker_outcome(
                str(inputs.get("status") or ""), dict(inputs)
            )

        result = FailureABGate(self.db_path).run(
            report_id=report_id,
            metric_id=metric_id,
            cases=cases,
            baseline=baseline,
            variants=[
                CandidateVariant("B1-explicit-cancellation", _variant_reject_requested),
                CandidateVariant("B2-strict-terminal", _variant_strict_terminal),
            ],
            independent_oracle=oracle,
        )
        return {
            **result,
            "status": "completed",
            "ab_verdict": result["status"],
            "replay_source": "correlated_worker_task_events",
            "stable_memory_written": False,
            "activated": False,
        }
