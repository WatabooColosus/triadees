"""`evaluation_provider` de vitalidad: mide el efecto real de un candidato.

`SelfImprovementOrchestrator.run_once()` (`triade/self_improvement/orchestrator.py`)
exige un `EvaluationProvider`:

    Callable[[str, dict], tuple[EvaluationRun, EvaluationRun, tuple[MetricPolicy, ...]]]

Hasta 2026-07-31 **no existía ninguno** en producción, y por eso el bucle de
automejora no podía cerrarse (auditoría, P0-02). Este módulo aporta el primero.

Principio de diseño
-------------------
No inventa puntuaciones: **lee las que el Verifier ya escribió** en
`verification_reports` durante runs reales. Compara dos ventanas de runs:

- **baseline**: runs anteriores a que el candidato estuviera activo.
- **candidate**: runs posteriores.

Es decir, mide el **efecto observado del candidato sobre la vitalidad de Tríade**,
no una autoevaluación declarativa.

Límite honesto y deliberado
---------------------------
Esto es una comparación **antes/después**, no un A/B controlado: no se ejecuta la
misma carga con y sin el candidato. Si en la ventana ocurrieron otros cambios, se
confunden con el efecto del candidato. Por eso:

- Exige un mínimo de runs en cada ventana (`min_runs`), y si no los hay **falla en
  vez de adivinar**.
- El `decision` que produce se apoya en `compare_evaluations`, y la promoción real
  además exige que `RegressionGate` dé `pass` con tolerancia cero en trazabilidad
  y safety.

Un A/B verdadero requeriría poder repetir la misma carga con y sin el candidato;
esa capacidad **no existe hoy** y queda registrada como trabajo pendiente.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from triade.evaluation.contracts import EvaluationRun, MetricResult
from triade.evaluation.triade_vitality_suite import (
    SUITE_ID,
    SUITE_VERSION,
    TRIADE_VITALITY_SUITE,
)
from triade.regression.gate import MetricPolicy

#: Columna en `verification_reports` → `metric_id` de la suite.
_METRIC_COLUMNS: dict[str, str] = {
    "coherence_score": "coherence",
    "memory_score": "memory",
    "safety_score": "safety",
    "usefulness_score": "usefulness",
    "traceability_score": "traceability",
}


class VitalityEvaluationProvider:
    """Construye baseline/candidate desde `verification_reports` reales."""

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        window: int = 30,
        min_runs: int = 10,
    ) -> None:
        self.db_path = Path(db_path)
        self.window = max(1, int(window))
        self.min_runs = max(1, int(min_runs))

    # ── lectura de evidencia real ──────────────────────────────────────
    def _rows(self, *, before: str | None, limit: int) -> list[sqlite3.Row]:
        columns = ", ".join(_METRIC_COLUMNS)
        sql = f"SELECT {columns}, created_at FROM verification_reports"
        params: list[Any] = []
        if before:
            sql += " WHERE created_at < ?"
            params.append(before)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return list(conn.execute(sql, params))

    @staticmethod
    def _aggregate(rows: list[sqlite3.Row]) -> dict[str, float]:
        totals = {metric: 0.0 for metric in _METRIC_COLUMNS.values()}
        for row in rows:
            for column, metric in _METRIC_COLUMNS.items():
                totals[metric] += float(row[column] or 0.0)
        count = max(1, len(rows))
        return {metric: value / count for metric, value in totals.items()}

    def _run(self, evaluation_id: str, subject_id: str, scores: dict[str, float]) -> EvaluationRun:
        results = tuple(
            MetricResult(
                case_id=metric,
                score=scores[metric],
                passed=scores[metric] >= 0.60,
                actual=round(scores[metric], 4),
                expected=0.60,
            )
            for metric in sorted(scores)
        )
        aggregate = sum(scores.values()) / max(1, len(scores))
        run = EvaluationRun(
            evaluation_id=evaluation_id,
            suite_id=SUITE_ID,
            suite_version=SUITE_VERSION,
            subject_id=subject_id,
            results=results,
            aggregate_score=aggregate,
            created_at=_now(),
            metadata={"source": "verification_reports", "window": self.window},
        )
        # La suite valida que no falte ninguna métrica requerida y que
        # suite_id/version coincidan. Falla ruidosamente si algo no cuadra.
        TRIADE_VITALITY_SUITE.validate_run(run)
        return run

    # ── interfaz EvaluationProvider ────────────────────────────────────
    def __call__(
        self, candidate_id: str, artifact: dict[str, Any]
    ) -> tuple[EvaluationRun, EvaluationRun, tuple[MetricPolicy, ...]]:
        cutoff = str(artifact.get("created_at") or artifact.get("started_at") or "")
        if not cutoff:
            raise ValueError(
                "el artifact del candidato debe traer created_at para separar "
                "baseline de candidate; sin corte temporal la comparación no es honesta"
            )

        candidate_rows = [
            row for row in self._rows(before=None, limit=self.window)
            if str(row["created_at"]) >= cutoff
        ]
        baseline_rows = self._rows(before=cutoff, limit=self.window)

        if len(baseline_rows) < self.min_runs:
            raise ValueError(
                f"evidencia insuficiente antes del candidato: {len(baseline_rows)} "
                f"runs, se exigen {self.min_runs}"
            )
        if len(candidate_rows) < self.min_runs:
            raise ValueError(
                f"evidencia insuficiente después del candidato: {len(candidate_rows)} "
                f"runs, se exigen {self.min_runs}. Hay que dejarlo operar más tiempo."
            )

        baseline = self._run(
            f"vitality-baseline-{candidate_id}", candidate_id, self._aggregate(baseline_rows)
        )
        candidate = self._run(
            f"vitality-candidate-{candidate_id}", candidate_id, self._aggregate(candidate_rows)
        )
        return baseline, candidate, TRIADE_VITALITY_SUITE.policies()


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()
