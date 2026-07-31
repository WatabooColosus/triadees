"""Aprender del fallo: convertir una cuarentena en el siguiente intento dirigido.

Origen (2026-07-31). El responsable del proyecto señaló dos huecos reales:

    "Si falla porque no pasa el umbral no existe algo para que aprenda sobre eso
     y mejore la forma de aprender en eso que falló hasta pasar el umbral."

    "Así mismo la interconexión entre neuronas ayuda a todas y al sistema Tríade."

Ambos eran ciertos y verificables antes de este módulo:

1. **El fallo no enseñaba nada.** `NeuronEvaluationRunner` mueve el candidato a
   `quarantined` (`neuron_factory/evaluation.py:131`) y ahí termina. El
   `RegressionReport` sabe exactamente *qué* métrica cayó y *cuánto*
   (`RegressionFinding`, `regression/gate.py:41`), pero nadie leía ese detalle
   para dirigir el intento siguiente. La transición `quarantined → training`
   existe en el contrato (`specification.py:25`) y **ningún** código la usaba.

2. **Nadie creaba señales en producción.** `ImprovementStore.register_signal`
   solo tenía llamadas desde tests: el ciclo de auto-mejora no tenía fuente de
   entrada real. Podía verificar con rigor, pero nunca arrancaba solo.

Este módulo cierra ambos, sin inventar métricas nuevas: **lee el veredicto que el
gate ya escribió** y lo devuelve al bucle como señal medida.

## Cómo "mejora la forma de aprender en eso que falló"

Cada fallo se archiva como *lección* en `improvement_failure_lessons`, indexada
por `(capability_id, metric_id)` — **no** por neurona. De ahí salen tres cosas:

- **Dirección**: la señal generada apunta a la métrica que realmente falló, con
  `observed_score` = lo que el candidato logró y `target_score` = el listón que
  no alcanzó. El intento siguiente no es a ciegas.
- **Memoria**: `lessons_for()` devuelve lo ya intentado y fallado, para que la
  hipótesis siguiente no repita la anterior.
- **Rendimiento decreciente**: `estimated_cost` crece con el número de intentos
  sobre la misma métrica, así que `ImprovementSignal.priority()` decae sola. Un
  umbral que resulta inalcanzable deja de consumir ciclos por sí mismo, sin que
  nadie tenga que intervenir. `MAX_ATTEMPTS` es el tope duro.

## Cómo la interconexión "ayuda a todas"

La lección se archiva por **capacidad**, no por neurona. Cualquier neurona que
declare esa capacidad en `provides_capabilities` hereda el historial completo de
fallos sin haberlos sufrido: no repite el intento que ya falló en otra.
`affected_neurons()` además expone las que la declaran en
`requires_capabilities` — las que *dependen* de esa capacidad y quedarían
degradadas si cae. Un fallo local se vuelve información del organismo.

## Lo que este módulo NO hace, deliberadamente

- **No relaja el gate.** Genera entradas al bucle; el veredicto sigue siendo de
  `RegressionGate` contra la suite inmutable `triade-vitality`. Aprender del
  fallo no es tolerarlo: trazabilidad y safety mantienen tolerancia cero.
- **No promueve nada, no toca `identity_core`, no activa ningún LoRA.**
- **No inventa el objetivo.** Si el informe no trae puntuaciones reales, la
  lección se archiva pero no se emite señal: falla en vez de adivinar.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .contracts import ImprovementSignal
from .store import ImprovementStore

#: Tope duro de intentos por `(capability_id, metric_id)`. `estimated_cost` ya
#: hace decaer la prioridad de forma continua; esto es el freno final para que un
#: umbral inalcanzable no pueda consumir ciclos de forma indefinida.
MAX_ATTEMPTS = 5

#: Cuánto pesa cada severidad del gate al traducirse a señal. `impact` es lo que
#: la métrica importa; `risk_level` es lo que arriesga tocarla.
_SEVERITY: dict[str, tuple[float, str]] = {
    "critical": (1.0, "critical"),
    "high": (0.8, "high"),
    "medium": (0.5, "medium"),
    "low": (0.3, "low"),
}

#: Una brecha por debajo de esto es ruido de coma flotante, no una degradación.
#: Mismo criterio que `triade_vitality_suite.FLOAT_NOISE`; si la brecha es ruido
#: no hay nada que aprender y `target_score <= observed_score` haría fallar
#: `ImprovementSignal.validate()` de todas formas.
MIN_REAL_GAP = 1e-6


class FailureLearningLoop:
    """Convierte informes de regresión reprobados en señales de mejora dirigidas."""

    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = Path(db_path)
        self.clock = clock
        self.store = ImprovementStore(db_path, clock=clock)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS improvement_failure_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability_id TEXT NOT NULL,
                    metric_id TEXT NOT NULL,
                    report_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    baseline_score REAL,
                    candidate_score REAL,
                    absolute_delta REAL,
                    reason TEXT NOT NULL,
                    signal_id TEXT,
                    created_at REAL NOT NULL,
                    UNIQUE (report_id, metric_id)
                );
                CREATE INDEX IF NOT EXISTS idx_failure_lesson_lookup
                    ON improvement_failure_lessons(capability_id, metric_id, id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Interconexión entre neuronas ───────────────────────────────────

    def lessons_for(
        self, capability_id: str, metric_id: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Historial de fallos de esa capacidad+métrica, de cualquier neurona.

        Indexado por capacidad y no por neurona a propósito: una neurona nueva
        hereda lo que ya falló en otra sin tener que fallarlo ella también.
        """
        with self._connect() as conn:
            if not _table_exists(conn, "improvement_failure_lessons"):
                return []
            rows = conn.execute(
                """SELECT * FROM improvement_failure_lessons
                   WHERE capability_id = ? AND metric_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (capability_id, metric_id, max(1, limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def attempts_for(self, capability_id: str, metric_id: str) -> int:
        """Cuántas veces se ha fallado ya esta métrica, en cualquier neurona."""
        with self._connect() as conn:
            if not _table_exists(conn, "improvement_failure_lessons"):
                return 0
            row = conn.execute(
                """SELECT COUNT(*) AS total FROM improvement_failure_lessons
                   WHERE capability_id = ? AND metric_id = ?""",
                (capability_id, metric_id),
            ).fetchone()
        return int(row["total"]) if row else 0

    def affected_neurons(self, capability_id: str) -> dict[str, list[str]]:
        """Quién provee esa capacidad y quién depende de ella.

        `provides` son las que pueden aprovechar la lección directamente.
        `requires` son las que quedan degradadas si la capacidad cae — el fallo
        de una neurona es información para el organismo, no solo para ella.
        """
        provides: list[str] = []
        requires: list[str] = []
        with self._connect() as conn:
            if not _table_exists(conn, "neuron_specifications"):
                return {"provides": [], "requires": []}
            rows = conn.execute(
                "SELECT neuron_id, payload_json FROM neuron_specifications"
            ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            neuron_id = str(row["neuron_id"])
            if capability_id in (payload.get("provides_capabilities") or ()):
                provides.append(neuron_id)
            if capability_id in (payload.get("requires_capabilities") or ()):
                requires.append(neuron_id)
        return {"provides": sorted(set(provides)), "requires": sorted(set(requires))}

    # ── Aprender del fallo ─────────────────────────────────────────────

    def harvest(self, *, limit: int = 5) -> dict[str, Any]:
        """Lee informes reprobados sin cosechar y emite señales dirigidas.

        Idempotente: `UNIQUE (report_id, metric_id)` impide que un mismo hallazgo
        genere dos lecciones, así que ejecutarlo dos veces sobre el mismo informe
        no duplica señales.
        """
        summary: dict[str, Any] = {
            "reports_seen": 0,
            "lessons_recorded": 0,
            "signals_created": 0,
            "exhausted": [],
            "signals": [],
            # Nada se descarta en silencio: un hallazgo sin puntuaciones o con
            # brecha de ruido queda listado con su motivo, no desaparece.
            "skipped": [],
        }
        with self._connect() as conn:
            if not _table_exists(conn, "regression_reports"):
                return summary
            reports = conn.execute(
                """SELECT report_id, candidate_id, capability, findings_json
                   FROM regression_reports WHERE decision = 'fail'
                   ORDER BY rowid DESC LIMIT ?""",
                (max(1, limit),),
            ).fetchall()

        for report in reports:
            summary["reports_seen"] += 1
            for finding in _failed_findings(report["findings_json"]):
                outcome = self._learn(dict(report), finding)
                if outcome is None:
                    continue
                summary["lessons_recorded"] += 1
                if outcome.get("exhausted"):
                    summary["exhausted"].append(outcome)
                elif outcome.get("signal_id"):
                    summary["signals_created"] += 1
                    summary["signals"].append(outcome)
                else:
                    summary["skipped"].append(outcome)
        return summary

    def _learn(
        self, report: dict[str, Any], finding: dict[str, Any]
    ) -> dict[str, Any] | None:
        capability = str(report.get("capability") or "")
        metric = str(finding.get("metric_id") or "")
        if not capability or not metric:
            return None

        # El intento se cuenta ANTES de archivar esta lección, de modo que el
        # primer fallo de una métrica tenga coste 1 y no 2.
        attempt = self.attempts_for(capability, metric) + 1
        severity = str(finding.get("severity") or "medium")
        baseline = _as_float(finding.get("baseline_score"))
        candidate = _as_float(finding.get("candidate_score"))
        reason = str(finding.get("reason") or "sin motivo declarado")

        lesson_id = self._record_lesson(report, finding, capability, metric, severity)
        if lesson_id is None:
            return None  # ya cosechada

        base = {
            "capability_id": capability,
            "metric_id": metric,
            "report_id": str(report.get("report_id") or ""),
            "attempt": attempt,
            "reason": reason,
        }

        if attempt > MAX_ATTEMPTS:
            # No se emite señal: se deja constancia de que se agotó el margen.
            # Ningún humano tiene que pararlo y ningún bucle queda girando.
            return {**base, "exhausted": True, "signal_id": None}

        # Sin puntuaciones reales no hay objetivo que perseguir: se archiva la
        # lección pero no se adivina una señal.
        if baseline is None or candidate is None:
            return {**base, "signal_id": None, "reason_skipped": "sin puntuaciones"}
        if baseline - candidate < MIN_REAL_GAP:
            return {
                **base,
                "signal_id": None,
                "reason_skipped": "brecha no significativa",
            }

        impact, risk = _SEVERITY.get(severity, (0.5, "medium"))
        signal = ImprovementSignal(
            signal_id=f"fail-{base['report_id']}-{metric}",
            capability_id=capability,
            metric_id=metric,
            observed_score=candidate,
            target_score=baseline,
            impact=impact,
            # Es una brecha MEDIDA por el gate, no una estimación. La confianza
            # baja con los intentos: si ya falló varias veces, la hipótesis de
            # que un intento más lo arregla vale menos.
            confidence=max(0.3, 1.0 - 0.15 * (attempt - 1)),
            # El coste crece con los intentos: `priority()` divide por él, así
            # que una métrica terca cede el turno sola.
            estimated_cost=float(attempt),
            risk_level=risk,
            source_ref=f"regression_report:{base['report_id']}",
        )
        try:
            self.store.register_signal(signal)
            signal_id, action = signal.signal_id, "created"
        except ValueError:
            # Ya hay una señal abierta para esta misma métrica: no se apila un
            # duplicado, se **afila la que existe** con la medición nueva (coste
            # mayor, confianza menor). Sin esto la señal quedaría congelada en el
            # primer intento y la escalada nunca surtiría efecto.
            refreshed = self.store.refresh_open_signal(signal)
            if refreshed is None:
                return {
                    **base,
                    "signal_id": None,
                    "reason_skipped": "señal no registrable",
                }
            signal_id, action = str(refreshed["signal_id"]), "refreshed"

        with self._connect() as conn:
            conn.execute(
                "UPDATE improvement_failure_lessons SET signal_id = ? WHERE id = ?",
                (signal_id, lesson_id),
            )
        return {
            **base,
            "signal_id": signal_id,
            "action": action,
            "priority": signal.priority(),
        }

    def _record_lesson(
        self,
        report: dict[str, Any],
        finding: dict[str, Any],
        capability: str,
        metric: str,
        severity: str,
    ) -> int | None:
        """Archiva la lección. Devuelve `None` si el hallazgo ya estaba cosechado."""
        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO improvement_failure_lessons
                   (capability_id, metric_id, report_id, candidate_id, severity,
                    baseline_score, candidate_score, absolute_delta, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    capability,
                    metric,
                    str(report.get("report_id") or ""),
                    str(report.get("candidate_id") or ""),
                    severity,
                    _as_float(finding.get("baseline_score")),
                    _as_float(finding.get("candidate_score")),
                    _as_float(finding.get("absolute_delta")),
                    str(finding.get("reason") or "sin motivo declarado"),
                    self.clock(),
                ),
            )
            if not cursor.rowcount or cursor.lastrowid is None:
                return None
            return int(cursor.lastrowid)

    def hypothesis_for(self, capability_id: str, metric_id: str) -> str:
        """Texto de hipótesis que incorpora lo ya intentado y fallado.

        Sirve para que la propuesta siguiente sea distinta de la anterior en vez
        de repetir a ciegas — y para que quede escrito por qué se intenta esto.
        """
        lessons = self.lessons_for(capability_id, metric_id, limit=3)
        if not lessons:
            return f"recuperar {metric_id} en {capability_id}"
        previos = "; ".join(
            f"intento previo cayó a {_fmt(item['candidate_score'])} "
            f"desde {_fmt(item['baseline_score'])} ({item['reason']})"
            for item in lessons
        )
        return (
            f"recuperar {metric_id} en {capability_id} con un enfoque distinto: "
            f"{previos}"
        )


def _failed_findings(findings_json: Any) -> Sequence[dict[str, Any]]:
    try:
        findings = json.loads(findings_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(findings, list):
        return ()
    return [
        item
        for item in findings
        if isinstance(item, dict) and item.get("status") == "fail"
    ]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def _as_float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: Any) -> str:
    return "?" if value is None else f"{float(value):.4f}"
