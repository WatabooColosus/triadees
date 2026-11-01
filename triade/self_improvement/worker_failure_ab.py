"""Reproducción autónoma A/B de clasificación de fallos de workers.

SÓLO usa resultados de tareas y eventos terminales relacionados por run/task id.
No crea fallos, no repite prompts, no escribe memoria estable y no cambia
la política del worker vivo. Los casos sin procedencia concordante se descartan.

Esto compara políticas de clasificación de incidentes, NO demuestra por sí
solo que una reparación funcional de una tarea arregle su causa de origen.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from triade.db import sqlite3
from triade.runtime.task_status import TERMINAL_FAILURE

from .failure_ab import CandidateVariant, FailureABGate, FailureCase

_FAILURE_METRIC = "worker_outcome_classification"
_SUPPORTED_STATUSES = frozenset(
    {"completed", "observed", "cancelled", "failed", "dead_letter", "timeout",
     "lease_lost", "blocked"}
)
_SOURCE_EVENT_LIMIT = 300
_MIN_CASES = 8


def _explicit_cancellation(payload: dict[str, Any]) -> bool:
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


def _variant_reject_requested(payload: dict[str, Any]) -> bool:
    status = str(payload["status"])
    if _explicit_cancellation(payload):
        return False
    return status in TERMINAL_FAILURE or status in {"blocked", "cancelled"}


def _variant_strict_terminal(payload: dict[str, Any]) -> bool:
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
            if not {"worker_events", "worker_tasks"} <= names:
                return []
            rows = conn.execute(
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
            observations.append({
                "event_id": int(row["event_id"]),
                "task_id": task_id,
                "status": status,
                "payload": payload,
                "expected": _classification_label(status, payload),
            })
        return sorted(observations, key=lambda x: x["event_id"])

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
                        evidence_ref=f"worker-event:{observation['event_id']}",
                        safety_critical=(split == "negative"),
                    )
                )
        return cases

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

        def baseline(inputs: dict[str, Any]) -> bool:
            return _should_learn_from_worker_outcome(
                str(inputs.get("status") or ""), inputs
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
