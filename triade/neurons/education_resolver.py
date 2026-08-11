"""Resuelve una lección preparada: mejoró, no cambió nada, o empeoró.

El circuito de educación neuronal moría en `lesson_prepared`. Medido el
2026-08-02 sobre producción: 7 sesiones con `baseline_score` y `post_score` a
NULL, `applied_run_count` 0 y `result='uncertain'`;
`neuron_education_applications` con **cero filas**; y `learning_evidence`
acumulando hipótesis en `pending` que nadie cerraba.

`lesson_prepared` no es prueba de aprendizaje efectivo: es prueba de que se
preparó material. Esta pieza es la que faltaba para que lo sea o deje de serlo.

Conservador a propósito
-----------------------
- Sin ``MIN_APPLIED_RUNS`` aplicaciones medidas, la respuesta es
  ``insufficient_evidence``. Decidir ``improved`` sin runs sería el autorreporte
  que hay que evitar: la neurona no puede certificarse a sí misma.
- Sin baseline no hay comparación posible, y comparar contra nada no es medir.
- ``degraded`` revierte **solo**, sin esperar a nadie, y deja constancia.
- ``improved`` promueve pero **conserva la versión anterior**: sin eso no habría
  rollback después.
- Es idempotente. Resolver dos veces no duplica promoción ni evidencia.

Autonomía
---------
Aplicar, medir y revertir son ``AUTO_EXPERIMENTAL`` en el registro de autonomía:
avanzan sin una persona porque son reversibles y quedan marcados. Promover a
**estable** es ``HUMAN_REQUIRED`` y no ocurre aquí.
"""

from __future__ import annotations

import json
import statistics
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.db import sqlite3

RESOLVER_VERSION = "neuron-education-resolver-1.0.0"

#: Runs medidos mínimos antes de decidir nada. Cinco es el mismo mínimo que usa
#: la evidencia de aprendizaje: por debajo, una racha corta parece una mejora.
MIN_APPLIED_RUNS = 5

#: Cuánto tiene que moverse la métrica para no ser ruido.
IMPROVEMENT_DELTA = 0.10
DEGRADATION_DELTA = -0.10

Decision = str  # improved | neutral | degraded | insufficient_evidence | no_target


def _now() -> str:
    return datetime.now(UTC).isoformat()


class NeuronEducationResolver:
    """Cierra el ciclo: aplicación medida → decisión → promoción o rollback."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _has_table(conn: sqlite3.Connection, name: str) -> bool:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            is not None
        )

    # ── selección ────────────────────────────────────────────────────
    def _next_session(self, conn: sqlite3.Connection) -> sqlite3.Row | None:
        if not self._has_table(conn, "neuron_education_sessions"):
            return None
        if self._has_table(conn, "neuron_education_applications"):
            # Una sesión que ya puede producir una decisión debe preceder a la
            # rotación de sesiones todavía inmaduras. En producción había tres
            # con siete runs medidos, pero el orden por ``finished_at`` elegía
            # primero otra con cero y el ciclo volvía a terminar en
            # ``insufficient_evidence``.
            ready = conn.execute(
                """SELECT * FROM neuron_education_sessions s
                WHERE s.state = 'lesson_prepared'
                  AND s.baseline_score IS NOT NULL
                  AND (SELECT COUNT(*)
                       FROM neuron_education_applications a
                       WHERE a.session_id=s.session_id
                         AND a.outcome_score IS NOT NULL) >= ?
                ORDER BY s.finished_at, s.created_at LIMIT 1""",
                (MIN_APPLIED_RUNS,),
            ).fetchone()
            if ready is not None:
                return ready
        # Rota entre sesiones. Ordenando solo por `created_at`, una sesion en
        # `insufficient_evidence` --que conserva el estado `lesson_prepared` a
        # proposito, esperando mas runs-- se elegia siempre y las demas no se
        # miraban nunca. `finished_at` avanza en cada resolucion, asi que la
        # menos revisada va primero.
        return conn.execute(
            "SELECT * FROM neuron_education_sessions "
            "WHERE state = 'lesson_prepared' "
            "ORDER BY finished_at, created_at LIMIT 1"
        ).fetchone()

    def _applications(self, conn: sqlite3.Connection, session_id: str) -> list[float]:
        if not self._has_table(conn, "neuron_education_applications"):
            return []
        return [
            float(r["outcome_score"])
            for r in conn.execute(
                "SELECT outcome_score FROM neuron_education_applications "
                "WHERE session_id = ? AND outcome_score IS NOT NULL",
                (session_id,),
            )
        ]

    # ── decisión ─────────────────────────────────────────────────────
    @staticmethod
    def _decide(
        baseline: float | None, scores: list[float]
    ) -> tuple[Decision, str, float | None]:
        if len(scores) < MIN_APPLIED_RUNS:
            return (
                "insufficient_evidence",
                (
                    f"{len(scores)} run(s) aplicados, mínimo {MIN_APPLIED_RUNS}. "
                    "Sin runs medidos, promover sería autorreporte."
                ),
                None,
            )
        if baseline is None:
            return (
                "insufficient_evidence",
                "sin baseline previo: comparar contra nada no es medir",
                round(statistics.mean(scores), 4),
            )
        post = round(statistics.mean(scores), 4)
        delta = round(post - float(baseline), 4)
        if delta >= IMPROVEMENT_DELTA:
            return "improved", f"delta {delta:+.4f} sobre {len(scores)} runs", post
        if delta <= DEGRADATION_DELTA:
            return "degraded", f"delta {delta:+.4f} sobre {len(scores)} runs", post
        return "neutral", f"delta {delta:+.4f}: dentro del ruido", post

    # ── efectos ──────────────────────────────────────────────────────
    def _record_event(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        neuron_id: Any,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if not self._has_table(conn, "neuron_education_events"):
            return
        conn.execute(
            "INSERT INTO neuron_education_events (session_id,neuron_id,event_type,"
            "payload_json,created_at) VALUES (?,?,?,?,?)",
            (
                session_id,
                neuron_id,
                event_type,
                json.dumps(payload, ensure_ascii=False),
                _now(),
            ),
        )

    def _resolve_evidence(
        self, conn: sqlite3.Connection, session_id: str, decision: Decision
    ) -> None:
        """Cierra la hipótesis que `lesson_prepared` dejó en `pending`."""
        if not self._has_table(conn, "learning_evidence"):
            return
        conn.execute(
            "UPDATE learning_evidence SET decision = ?, updated_at = ? "
            "WHERE candidate_id = ? AND decision = 'pending'",
            (decision, _now(), f"neuron-education:{session_id}"),
        )

    # ── entrada ──────────────────────────────────────────────────────
    def resolve_once(self) -> dict[str, Any]:
        """Resuelve una sesión. Devuelve siempre un diccionario explicado."""
        try:
            conn = self._connect()
        except sqlite3.Error as exc:
            return {
                "decision": "no_target",
                "reason": f"db_error: {type(exc).__name__}: {exc}",
                "resolver_version": RESOLVER_VERSION,
            }
        try:
            with conn:
                sesion = self._next_session(conn)
                if sesion is None:
                    return {
                        "decision": "no_target",
                        "reason": "ninguna sesión en lesson_prepared",
                        "resolver_version": RESOLVER_VERSION,
                    }

                session_id = str(sesion["session_id"])
                neuron_id = sesion["neuron_id"]
                baseline = sesion["baseline_score"]
                scores = self._applications(conn, session_id)
                decision, motivo, post = self._decide(
                    None if baseline is None else float(baseline), scores
                )

                # La versión anterior se conserva SIEMPRE que se toca la sesión:
                # sin ella no hay rollback posible más adelante, ni para
                # promover ni para revertir.
                rollback_ref = str(sesion["rollback_ref"] or "") or (
                    f"neuron-{neuron_id}-pre-{session_id}-{uuid.uuid4().hex[:8]}"
                )

                nuevo_estado = {
                    "improved": "applied_improved",
                    "neutral": "applied_neutral",
                    "degraded": "rolled_back",
                    "insufficient_evidence": "lesson_prepared",
                }[decision]
                rolled_back = decision == "degraded"

                conn.execute(
                    "UPDATE neuron_education_sessions SET state=?, result=?, "
                    "post_score=?, applied_run_count=?, rollback_ref=?, "
                    "finished_at=? WHERE session_id=?",
                    (
                        nuevo_estado,
                        decision,
                        post,
                        len(scores),
                        rollback_ref,
                        # `finished_at` es NOT NULL en el esquema real. Se
                        # descubrió al correr contra una copia de produccion:
                        # el esquema de la prueba era mas permisivo que el de
                        # verdad, que es como se cuela un fallo asi.
                        _now(),
                        session_id,
                    ),
                )
                self._record_event(
                    conn,
                    session_id,
                    neuron_id,
                    f"education_{decision}",
                    {
                        "baseline": baseline,
                        "post": post,
                        "applied_runs": len(scores),
                        "reason": motivo,
                        "rollback_ref": rollback_ref,
                        "rolled_back": rolled_back,
                    },
                )
                # `insufficient_evidence` NO cierra la hipótesis: la sesión sigue
                # viva esperando más runs. Cerrarla seria declarar un veredicto
                # que no se ha alcanzado.
                if decision != "insufficient_evidence":
                    self._resolve_evidence(conn, session_id, decision)

                return {
                    "decision": decision,
                    "reason": motivo,
                    "session_id": session_id,
                    "neuron_id": neuron_id,
                    "baseline": baseline,
                    "post_score": post,
                    "applied_runs": len(scores),
                    "rollback_ref": rollback_ref,
                    "rolled_back": rolled_back,
                    "state": nuevo_estado,
                    "resolver_version": RESOLVER_VERSION,
                }
        finally:
            conn.close()
