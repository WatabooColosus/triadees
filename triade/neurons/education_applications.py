"""Registra cómo le fue a la neurona en los runs posteriores a su lección.

Era la última pieza que faltaba del ciclo. `NeuronEducationResolver` decide
sobre `neuron_education_applications`, y esa tabla tenía **cero filas**: sin runs
medidos sólo podía responder `insufficient_evidence`.

No se inventa ninguna métrica. Los dos datos existían por separado y nadie los
unía:

* ``neuron_activity`` — qué neurona se activó en qué run;
* ``verification_reports`` — cinco puntuaciones por run, escritas por el
  Verifier durante runs reales.

En producción **162 filas cruzan por `run_id`**. Este módulo es esa unión.

Sobre la atribución
-------------------
Que una neurona participe en un run no significa que ese run saliera bien *por
ella*. Es un proxy, no una prueba de causalidad. Por eso:

* sólo cuentan runs donde la neurona **se activó** de verdad;
* el baseline usa **la misma neurona y la misma métrica**, antes de la lección,
  y no se recalcula después — moverlo invalidaría la comparación ya hecha;
* un run sin informe de verificación **se ignora**, no cuenta como cero:
  «no medido» no es «malo», y contarlo hundiría la media fabricando una
  degradación que nadie observó;
* una caída de ``safety_score`` cuenta como regresión aunque la media suba.

Y por eso el resolutor exige varios runs y trata ``neutral`` como resultado
legítimo: con un proxy, lo honesto es un umbral conservador.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.db import sqlite3

RECORDER_VERSION = "neuron-education-applications-1.0.0"

#: Puntuaciones del Verifier que componen la medida de un run.
SCORE_COLUMNS = (
    "coherence_score",
    "memory_score",
    "safety_score",
    "usefulness_score",
    "traceability_score",
)

#: Por debajo de esto, la seguridad del run se considera una regresión aunque el
#: resto de puntuaciones suban.
SAFETY_REGRESSION_THRESHOLD = 0.6


def _now() -> str:
    return datetime.now(UTC).isoformat()


class NeuronEducationApplicationRecorder:
    """Une actividad neuronal con calidad medida del run."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _has_tables(conn: sqlite3.Connection, *names: str) -> bool:
        existentes = {
            str(r[0])
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        return all(n in existentes for n in names)

    # ── medición ─────────────────────────────────────────────────────
    @staticmethod
    def _score(fila: sqlite3.Row) -> float | None:
        valores = [float(fila[c]) for c in SCORE_COLUMNS if fila[c] is not None]
        if not valores:
            return None
        return round(statistics.mean(valores), 4)

    def _runs_de_la_neurona(
        self,
        conn: sqlite3.Connection,
        neuron_id: Any,
        *,
        desde: str | None,
        hasta: str | None,
    ) -> list[sqlite3.Row]:
        """Runs con informe donde esa neurona se activó, en la ventana pedida.

        El `JOIN` es lo que faltaba: `neuron_activity` sabe quién participó y
        `verification_reports` sabe cómo salió, y nadie los cruzaba.
        """
        columnas = ", ".join(f"vr.{c}" for c in SCORE_COLUMNS)
        sql = (
            f"SELECT DISTINCT na.run_id AS run_id, {columnas} "
            "FROM neuron_activity na "
            "JOIN verification_reports vr ON vr.run_id = na.run_id "
            "WHERE na.neuron_id = ? AND na.activated = 1"
        )
        params: list[Any] = [neuron_id]
        # `datetime()` en ambos lados y no comparación de texto: las dos tablas
        # escriben formatos distintos --`neuron_activity` usa espacio
        # (`2026-08-02 08:23:23`), la sesión usa ISO con `T` y desfase-- y en
        # texto el espacio (0x20) ordena ANTES que la `T` (0x54). Un run
        # posterior a la lección el MISMO día salía «anterior»: se descartaba de
        # las aplicaciones y entraba en el baseline, invirtiendo justo la
        # medida que esta pieza existe para hacer.
        if desde is not None:
            sql += " AND datetime(na.created_at) > datetime(?)"
            params.append(desde)
        if hasta is not None:
            sql += " AND datetime(na.created_at) <= datetime(?)"
            params.append(hasta)
        return list(conn.execute(sql + " ORDER BY na.run_id", params))

    # ── entrada ──────────────────────────────────────────────────────
    def record_once(self) -> dict[str, Any]:
        """Registra aplicaciones y baseline de las sesiones abiertas."""
        try:
            conn = self._connect()
        except sqlite3.Error as exc:
            return {
                "sessions_seen": 0,
                "applications_added": 0,
                "reason": f"db_error: {type(exc).__name__}: {exc}",
                "recorder_version": RECORDER_VERSION,
            }
        try:
            with conn:
                if not self._has_tables(
                    conn,
                    "neuron_education_sessions",
                    "neuron_education_applications",
                    "neuron_activity",
                    "verification_reports",
                ):
                    return {
                        "sessions_seen": 0,
                        "applications_added": 0,
                        "reason": "faltan tablas del circuito de educación",
                        "recorder_version": RECORDER_VERSION,
                    }

                sesiones = list(
                    conn.execute(
                        "SELECT session_id, neuron_id, created_at, baseline_score "
                        "FROM neuron_education_sessions "
                        "WHERE state = 'lesson_prepared'"
                    )
                )
                añadidas = 0
                detalle: list[dict[str, Any]] = []

                for sesion in sesiones:
                    session_id = str(sesion["session_id"])
                    neuron_id = sesion["neuron_id"]
                    leccion = str(sesion["created_at"])

                    # Baseline: la misma neurona antes de la lección. Sólo una
                    # vez; recalcularlo invalidaría la comparación ya hecha.
                    if sesion["baseline_score"] is None:
                        previos = [
                            s
                            for s in (
                                self._score(f)
                                for f in self._runs_de_la_neurona(
                                    conn, neuron_id, desde=None, hasta=leccion
                                )
                            )
                            if s is not None
                        ]
                        if previos:
                            conn.execute(
                                "UPDATE neuron_education_sessions "
                                "SET baseline_score = ? WHERE session_id = ?",
                                (round(statistics.mean(previos), 4), session_id),
                            )

                    ya = {
                        str(r["run_id"])
                        for r in conn.execute(
                            "SELECT run_id FROM neuron_education_applications "
                            "WHERE session_id = ?",
                            (session_id,),
                        )
                    }
                    nuevas = 0
                    regresiones = 0
                    for fila in self._runs_de_la_neurona(
                        conn, neuron_id, desde=leccion, hasta=None
                    ):
                        run_id = str(fila["run_id"])
                        if run_id in ya:
                            continue
                        score = self._score(fila)
                        if score is None:
                            # No medido no es malo: se ignora en vez de contarlo
                            # como cero y fabricar una degradación.
                            continue
                        seguridad = fila["safety_score"]
                        if (
                            seguridad is not None
                            and float(seguridad) < SAFETY_REGRESSION_THRESHOLD
                        ):
                            regresiones += 1
                        conn.execute(
                            "INSERT INTO neuron_education_applications "
                            "(session_id,run_id,outcome_score,evidence_ref,created_at)"
                            " VALUES (?,?,?,?,?)",
                            (
                                session_id,
                                run_id,
                                score,
                                f"verification_reports:{run_id}",
                                _now(),
                            ),
                        )
                        nuevas += 1

                    if nuevas or regresiones:
                        conn.execute(
                            "UPDATE neuron_education_sessions SET "
                            "applied_run_count = (SELECT COUNT(*) FROM "
                            "neuron_education_applications WHERE session_id = ?), "
                            "regression_count = regression_count + ? "
                            "WHERE session_id = ?",
                            (session_id, regresiones, session_id),
                        )
                    añadidas += nuevas
                    detalle.append(
                        {
                            "session_id": session_id,
                            "neuron_id": neuron_id,
                            "added": nuevas,
                            "regressions": regresiones,
                        }
                    )

                return {
                    "sessions_seen": len(sesiones),
                    "applications_added": añadidas,
                    "sessions": detalle,
                    "recorder_version": RECORDER_VERSION,
                }
        finally:
            conn.close()
