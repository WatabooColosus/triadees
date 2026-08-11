"""Observación del canary entre ciclos del worker.

Por qué esto es una tarea aparte
--------------------------------
`SelfImprovementOrchestrator.run_once()` termina en `canary_running`: la
candidata quedó promovida a *candidata promovida* y su canary abierto. Ahí
se detiene, y es correcto que lo haga. Un canary necesita observaciones reales
—runs del sistema con la candidata activa— y esperarlas dentro de la evaluación
significaría bloquear un worker durante horas sosteniendo un lease.

Así que el canary se observa después, en ciclos posteriores, acumulando
evidencia. Ese es el único modo de que la observación sea real y no simulada.

Idempotencia
------------
La garantía "no contar dos veces el mismo informe" no se deja a una comprobación
en código: vive en la clave primaria de
`improvement_canary_consumed_reports(canary_id, report_id)`. Aunque dos tareas
llegasen a la vez —no deberían, la clave de exclusión por `candidate_id` lo
impide— la base rechazaría el duplicado.

Qué NO hace
-----------
No promueve nada a estable. Un canary graduado significa "sobrevivió a la
ventana de observación sin degradar", no "consolidado". La promoción estable
sigue siendo un carril crítico serial y, si la política exige firma humana, la
sigue exigiendo. Aquí solo se declara la elegibilidad.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from triade.db import sqlite3

from .canary import CanaryMonitor

#: Las mismas cinco columnas que mide `VitalityEvaluationProvider`. La
#: observación tiene que puntuar con la misma vara con la que se evaluó, o la
#: comparación contra `baseline_score` no significaría nada.
_METRIC_COLUMNS = (
    "coherence_score",
    "memory_score",
    "safety_score",
    "usefulness_score",
    "traceability_score",
)


class CanaryObservationCollector:
    """Alimenta el canary activo con informes de verificación reales."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.canary = CanaryMonitor(self.db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS improvement_canary_consumed_reports (
                    canary_id TEXT NOT NULL,
                    report_id INTEGER NOT NULL,
                    score REAL NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (canary_id, report_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    # ── lectura ─────────────────────────────────────────────────────────
    def active_canary(self, candidate_id: str | None = None) -> dict[str, Any] | None:
        """El canary en curso, opcionalmente el de una candidata concreta."""
        sql = "SELECT * FROM improvement_canaries WHERE status = 'running'"
        params: list[Any] = []
        if candidate_id:
            sql += " AND candidate_id = ?"
            params.append(candidate_id)
        sql += " ORDER BY created_at ASC LIMIT 1"
        with self._connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='improvement_canaries'"
            ).fetchone():
                return None
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _unconsumed_reports(self, canary_id: str, since: float) -> list[sqlite3.Row]:
        """Informes posteriores al arranque del canary que aún no se contaron.

        **Limitación que no se puede disimular**: "posterior al canary" es
        correlación temporal, no prueba de que la candidata haya servido nada.
        Hoy no existe enrutado de tráfico por candidata, así que no hay forma de
        saber qué informes se produjeron *con* ella activa. Un cambio ajeno
        ocurrido en la misma ventana se le atribuiría igual.

        Por eso el resultado se marca `causal_attribution: "temporal_only"` y el
        canary **no promueve nada**: solo puede mantener, graduar como elegible o
        revertir. Un rollback por correlación es aceptable —revertir de más es
        barato—; una promoción por correlación no lo sería.
        """
        columns = ", ".join(_METRIC_COLUMNS)
        with self._connect() as conn:
            return list(
                conn.execute(
                    f"""SELECT v.id, {columns}, v.created_at
                    FROM verification_reports v
                    LEFT JOIN improvement_canary_consumed_reports c
                      ON c.canary_id = ? AND c.report_id = v.id
                    WHERE c.report_id IS NULL AND v.created_at > ?
                    ORDER BY v.id ASC""",
                    (canary_id, _iso_from_epoch(since)),
                )
            )

    @staticmethod
    def _score(row: sqlite3.Row) -> float:
        values = [float(row[column] or 0.0) for column in _METRIC_COLUMNS]
        return sum(values) / len(values)

    # ── observación ─────────────────────────────────────────────────────
    def observe_once(
        self, *, candidate_id: str | None = None, max_reports: int = 5
    ) -> dict[str, Any]:
        """Aplica al canary los informes nuevos y devuelve su estado.

        `max_reports` acota cuánto se consume por ciclo: si se volcaran cincuenta
        informes de golpe, el canary saltaría de recién abierto a graduado sin que
        nadie hubiera podido reaccionar a una degradación intermedia.
        """
        canary = self.active_canary(candidate_id)
        if canary is None:
            return {"status": "no_canary", "reason": "no hay canary en curso"}

        canary_id = str(canary["canary_id"])
        pending = self._unconsumed_reports(canary_id, float(canary["created_at"]))
        if not pending:
            return {
                "status": "insufficient_candidate_observations",
                "reason": (
                    "no hay informes de verificación nuevos posteriores al canary; "
                    "hay que dejar operar al sistema más tiempo"
                ),
                "canary_id": canary_id,
                "candidate_id": str(canary["candidate_id"]),
                "observation_count": int(canary["payload_json"] and 0),
            }

        applied: list[dict[str, Any]] = []
        outcome: dict[str, Any] = {}
        for row in pending[: max(1, int(max_reports))]:
            report_id = int(row["id"])
            score = self._score(row)
            # Se reserva el informe ANTES de contarlo. Si el proceso muriera
            # entre ambas cosas preferimos perder una observación a contar dos
            # veces la misma: inflar la evidencia de un canary es peor que
            # quedarse corto.
            if not self._reserve(canary_id, report_id, score):
                continue
            outcome = self.canary.observe(
                canary_id,
                score=score,
                metadata={"source": "verification_reports", "report_id": report_id},
            )
            applied.append({"report_id": report_id, "score": round(score, 6)})
            if outcome.get("status") != "running":
                break

        if not applied:
            return {
                "status": "insufficient_candidate_observations",
                "reason": "todos los informes disponibles ya estaban contados",
                "canary_id": canary_id,
                "candidate_id": str(canary["candidate_id"]),
            }

        status = str(outcome.get("status") or "running")
        return {
            "status": status,
            "canary_id": canary_id,
            "candidate_id": str(canary["candidate_id"]),
            "applied_observations": applied,
            "observation_count": int(outcome.get("observation_count") or len(applied)),
            "average_score": outcome.get("average_score"),
            "lower_bound": outcome.get("lower_bound"),
            "rollback": outcome.get("rollback"),
            # Graduado NO es promovido. Solo declara que la candidata sobrevivió
            # la ventana sin degradar; consolidarla sigue siendo otro carril.
            "eligible_for_stable_promotion": status == "graduated",
            "stable_promotion_performed": False,
            # Ni A/B ni prueba de uso: los informes se atribuyen a la candidata
            # por ser posteriores al canary, nada más. Quien lea este resultado
            # tiene que poder saberlo sin ir a leer el código.
            "causal_attribution": "temporal_only",
            "causal_attribution_note": (
                "Los informes se seleccionan por ser posteriores al arranque del "
                "canary. No hay enrutado de tráfico por candidata, así que no se "
                "demuestra que la candidata sirviera esas respuestas."
            ),
        }

    def _reserve(self, canary_id: str, report_id: int, score: float) -> bool:
        """Marca el informe como consumido. `False` si ya lo estaba."""
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO improvement_canary_consumed_reports
                    (canary_id, report_id, score, created_at) VALUES (?, ?, ?, ?)""",
                    (canary_id, report_id, score, time.time()),
                )
            except sqlite3.IntegrityError:
                return False
        return True


def _iso_from_epoch(value: float) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(value, tz=UTC).isoformat()
