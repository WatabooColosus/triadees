"""A/B de reparaciones de fallos: evidencia independiente, no prompts forzados.

El módulo sólo compara implementaciones confiables ejecutadas por un llamador
autorizado. Nunca evalúa código generado, altera workers, aprueba una neurona,
ni transforma por sí mismo un resultado en memoria estable.

Se exige un RegressionReport *fallido* real y un oráculo externo por caso,
proveniente de una fuente verificable que la variante no pueda escribir.
Los casos se reservan ANTES de comparar versiones. El holdout se consulta
una sola vez para la variante elegida con los datos de entrenamiento.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from triade.db import sqlite3

AB_PROTOCOL_VERSION = "failure-ab-1"
SPLITS = frozenset({"train", "holdout", "negative"})
MAX_VARIANTS = 4
MAX_CASES = 60
MIN_TRAIN = 3
MIN_HOLDOUT = 3
MIN_NEGATIVE = 2
MIN_GAIN = 0.20

Evaluator = Callable[[Mapping[str, Any]], Any]
Oracle = Callable[["FailureCase"], bool]


@dataclass(frozen=True)
class FailureCase:
    case_id: str
    split: str
    inputs: Mapping[str, Any]
    expected: Any
    evidence_ref: str
    safety_critical: bool = False


@dataclass(frozen=True)
class CandidateVariant:
    version: str
    evaluator: Evaluator


class FailureABGate:
    """Compara A con B1..Bn sin contaminar holdout ni tocar producción."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @staticmethod
    def _digest(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()

    @staticmethod
    def _validate_cases(cases: Sequence[FailureCase], oracle: Oracle | None) -> None:
        if oracle is None or not callable(oracle):
            raise ValueError("independent_oracle_required")
        if not MIN_TRAIN + MIN_HOLDOUT + MIN_NEGATIVE <= len(cases) <= MAX_CASES:
            raise ValueError("invalid_case_budget")
        ids, refs = set(), set()
        counts = {split: 0 for split in SPLITS}
        for case in cases:
            if (
                not case.case_id or case.case_id in ids
                or case.split not in SPLITS
                or not case.evidence_ref or case.evidence_ref in refs
            ):
                raise ValueError("duplicated_or_unattested_case")
            ids.add(case.case_id)
            refs.add(case.evidence_ref)
            counts[case.split] += 1
            if not oracle(case):
                raise ValueError("case_origin_not_independently_verified")
        if (
            counts["train"] < MIN_TRAIN
            or counts["holdout"] < MIN_HOLDOUT
            or counts["negative"] < MIN_NEGATIVE
        ):
            raise ValueError("incomplete_independent_splits")
        if not any(c.safety_critical for c in cases if c.split != "train"):
            raise ValueError("missing_safety_control")

    def _failure_origin(self, report_id: str, metric_id: str) -> dict[str, Any]:
        # Consultar el gate real, no confiar en el texto de un candidato.
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT report_id,capability,decision,findings_json "
                "FROM regression_reports WHERE report_id=?", (report_id,)
            ).fetchone()
        if row is None or row["decision"] != "fail":
            raise ValueError("verified_failed_regression_required")
        try:
            findings = json.loads(row["findings_json"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_regression_evidence") from exc
        matching = [
            x for x in findings
            if isinstance(x, dict) and x.get("metric_id") == metric_id
            and x.get("status") == "fail"
        ]
        if len(matching) != 1:
            raise ValueError("measured_failing_metric_required")
        item = matching[0]
        baseline, candidate = item.get("baseline_score"), item.get("candidate_score")
        if (
            isinstance(baseline, bool) or isinstance(candidate, bool)
            or not isinstance(baseline, (float, int))
            or not isinstance(candidate, (float, int))
            or not math.isfinite(baseline) or not math.isfinite(candidate)
            or baseline <= candidate
        ):
            raise ValueError("measured_regression_gap_required")
        return {"report_id": report_id, "capability": row["capability"],
                "metric_id": metric_id, "observed_gap": baseline - candidate}

    @staticmethod
    def _score(evaluator: Evaluator, cases: Sequence[FailureCase]) -> tuple[float, list[dict[str, Any]]]:
        observations = []
        for case in cases:
            try:
                actual = evaluator(dict(case.inputs))
                passed = type(actual) is type(case.expected) and actual == case.expected
            except Exception as exc:  # evaluador confiable aislado; cualquier fallo reprueba
                passed = False
                actual = None
                error = type(exc).__name__
            else:
                error = None
            observations.append({
                "case_id": case.case_id,
                "split": case.split,
                "passed": bool(passed),
                "critical": case.safety_critical,
                "error_type": error,
            })
        return sum(x["passed"] for x in observations) / len(observations), observations

    def run(
        self,
        *,
        report_id: str,
        metric_id: str,
        cases: Sequence[FailureCase],
        baseline: Evaluator,
        variants: Sequence[CandidateVariant],
        independent_oracle: Oracle | None,
    ) -> dict[str, Any]:
        """Una competición A/B por conjunto sellado. No crea sucesores artificiales.

        El entrenamiento elige B; holdout y controles negativos sólo se ejecutan
        para el ganador. Un nuevo intento exige un conjunto independiente nuevo.
        """
        source = self._failure_origin(report_id, metric_id)
        self._validate_cases(cases, independent_oracle)
        if not 1 <= len(variants) <= MAX_VARIANTS:
            raise ValueError("invalid_variant_budget")
        versions = [v.version for v in variants]
        if (
            len(set(versions)) != len(versions)
            or any(not re.fullmatch(r"[a-zA-Z0-9_.-]{1,48}", v) for v in versions)
            or any(not callable(v.evaluator) for v in variants)
            or not callable(baseline)
        ):
            raise ValueError("invalid_candidate_versions")
        # Identidad de intento e inmutabilidad de casos, incluido el oráculo.
        suite = [{
            "case_id": c.case_id, "split": c.split,
            "evidence_ref": c.evidence_ref, "expected_digest": self._digest(c.expected),
            "inputs_digest": self._digest(c.inputs), "critical": c.safety_critical,
        } for c in cases]
        suite_hash = self._digest(suite)
        experiment_id = self._digest(
            [AB_PROTOCOL_VERSION, report_id, metric_id, suite_hash]
        )[:32]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS failure_ab_experiments ("
                "experiment_id TEXT PRIMARY KEY, report_id TEXT NOT NULL, "
                "metric_id TEXT NOT NULL, suite_hash TEXT NOT NULL, "
                "result_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            prior = conn.execute(
                "SELECT result_json FROM failure_ab_experiments WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
        if prior:
            return json.loads(prior[0])

        train = [c for c in cases if c.split == "train"]
        holdout = [c for c in cases if c.split == "holdout"]
        negative = [c for c in cases if c.split == "negative"]
        a_train, a_train_runs = self._score(baseline, train)
        all_training = []
        for variant in variants:
            score, obs = self._score(variant.evaluator, train)
            all_training.append({
                "version": variant.version, "score": score, "train_observations": obs
            })
        winner_index = max(
            range(len(variants)), key=lambda n: (all_training[n]["score"], -n)
        )
        winner = variants[winner_index]
        b_train = all_training[winner_index]["score"]
        result: dict[str, Any] = {
            "status": "insufficient_improvement", "experiment_id": experiment_id,
            "source": source, "suite_hash": suite_hash, "protocol": AB_PROTOCOL_VERSION,
            "train_baseline": a_train, "train_variants": all_training,
            "winner": winner.version, "holdout_executed": False,
            "eligible_for_canary": False, "stable_memory_written": False,
            "causal_attribution": "paired_offline_replay_only",
            "train_baseline_observations": a_train_runs,
        }
        if b_train - a_train >= MIN_GAIN:
            a_held, a_held_obs = self._score(baseline, holdout)
            b_held, b_held_obs = self._score(winner.evaluator, holdout)
            a_neg, a_neg_obs = self._score(baseline, negative)
            b_neg, b_neg_obs = self._score(winner.evaluator, negative)
            critical_ok = all(x["passed"] for x in b_held_obs + b_neg_obs if x["critical"])
            eligible = (
                b_held - a_held >= MIN_GAIN and b_neg >= a_neg and critical_ok
            )
            result.update({
                "status": "eligible_for_governed_review" if eligible else "regressed_or_no_transfer",
                "eligible_for_canary": eligible,
                "holdout_executed": True,
                "holdout_baseline": a_held, "holdout_candidate": b_held,
                "negative_baseline": a_neg, "negative_candidate": b_neg,
                "critical_controls_passed": critical_ok,
                "holdout_observations": {"A": a_held_obs, "B": b_held_obs},
                "negative_observations": {"A": a_neg_obs, "B": b_neg_obs},
            })
        # INSERT OR IGNORE preserva el primer veredicto frente a reintentos.
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO failure_ab_experiments "
                "(experiment_id,report_id,metric_id,suite_hash,result_json) VALUES (?,?,?,?,?)",
                (experiment_id, report_id, metric_id, suite_hash,
                 json.dumps(result, ensure_ascii=False, sort_keys=True)),
            )
            stored = conn.execute(
                "SELECT result_json FROM failure_ab_experiments WHERE experiment_id=?",
                (experiment_id,),
            ).fetchone()
        return json.loads(stored[0])
