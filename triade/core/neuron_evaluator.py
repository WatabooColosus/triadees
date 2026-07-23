"""Neuron Evaluator · métricas individuales por neurona.

Evalúa cada neurona individualmente: tasa de éxito, score promedio,
frecuencia de uso, última actividad, tendencia de rendimiento.
Genera un score compuesto para ranking y promoción.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

_METRICS_TABLE = """
CREATE TABLE IF NOT EXISTS neuron_eval_metrics (
    neuron_id INTEGER PRIMARY KEY,
    neuron_name TEXT NOT NULL,
    total_activations INTEGER DEFAULT 0,
    successful_activations INTEGER DEFAULT 0,
    failed_activations INTEGER DEFAULT 0,
    avg_score REAL DEFAULT 0.0,
    ema_score REAL DEFAULT 0.0,
    last_activation_at REAL DEFAULT 0.0,
    first_activation_at REAL DEFAULT 0.0,
    avg_response_ms REAL DEFAULT 0.0,
    composite_score REAL DEFAULT 0.0,
    trend TEXT DEFAULT 'stable',
    domain TEXT DEFAULT '',
    status TEXT DEFAULT 'candidate',
    updated_at REAL NOT NULL
);
"""

_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS neuron_activation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neuron_id INTEGER NOT NULL,
    neuron_name TEXT NOT NULL,
    activated_at REAL NOT NULL,
    score REAL DEFAULT 0.5,
    success INTEGER DEFAULT 1,
    response_ms REAL DEFAULT 0.0,
    source TEXT DEFAULT 'unknown',
    context TEXT DEFAULT ''
);
"""

_EMA_ALPHA = 0.3


class NeuronEvaluator:
    """Evalúa rendimiento individual de cada neurona."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(_METRICS_TABLE)
            conn.execute(_HISTORY_TABLE)

    def record_activation(
        self,
        neuron_id: int,
        neuron_name: str,
        score: float = 0.5,
        success: bool = True,
        response_ms: float = 0.0,
        source: str = "unknown",
        context: str = "",
        domain: str = "",
        status: str = "candidate",
    ) -> None:
        """Registra una activación de neurona y actualiza métricas."""
        now = time.time()

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO neuron_activation_history
                   (neuron_id, neuron_name, activated_at, score, success, response_ms, source, context)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (neuron_id, neuron_name, now, score, 1 if success else 0, response_ms, source, context),
            )

            row = conn.execute(
                "SELECT * FROM neuron_eval_metrics WHERE neuron_id = ?", (neuron_id,)
            ).fetchone()

            if row is None:
                conn.execute(
                    """INSERT INTO neuron_eval_metrics
                       (neuron_id, neuron_name, total_activations, successful_activations,
                        failed_activations, avg_score, ema_score, last_activation_at,
                        first_activation_at, avg_response_ms, composite_score, domain, status, updated_at)
                       VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        neuron_id, neuron_name,
                        1 if success else 0,
                        0 if success else 1,
                        score, score, now, now, response_ms,
                        score, domain, status, now,
                    ),
                )
            else:
                total = row["total_activations"] + 1
                successful = row["successful_activations"] + (1 if success else 0)
                failed = row["failed_activations"] + (0 if success else 1)
                new_ema = _EMA_ALPHA * score + (1 - _EMA_ALPHA) * row["ema_score"]
                new_avg_score = (row["avg_score"] * row["total_activations"] + score) / total
                new_avg_response = (row["avg_response_ms"] * row["total_activations"] + response_ms) / total

                composite = self._compute_composite(
                    avg_score=new_avg_score,
                    ema_score=new_ema,
                    success_rate=successful / total if total > 0 else 0,
                    total_activations=total,
                    last_activation=now,
                    first_activation=row["first_activation_at"] or now,
                    avg_response_ms=new_avg_response,
                )
                trend = self._compute_trend(new_ema, row["ema_score"])

                conn.execute(
                    """UPDATE neuron_eval_metrics SET
                       total_activations = ?, successful_activations = ?,
                       failed_activations = ?, avg_score = ?, ema_score = ?,
                       last_activation_at = ?, avg_response_ms = ?,
                       composite_score = ?, trend = ?, domain = ?, status = ?, updated_at = ?
                       WHERE neuron_id = ?""",
                    (total, successful, failed, round(new_avg_score, 4), round(new_ema, 4),
                     now, round(new_avg_response, 2), round(composite, 4), trend,
                     domain or row["domain"], status or row["status"], now, neuron_id),
                )

    def get_neuron_metrics(self, neuron_id: int) -> dict[str, Any] | None:
        """Retorna métricas de una neurona."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM neuron_eval_metrics WHERE neuron_id = ?", (neuron_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_neuron_history(self, neuron_id: int, limit: int = 50) -> list[dict[str, Any]]:
        """Retorna historial de activaciones de una neurona."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM neuron_activation_history WHERE neuron_id = ? ORDER BY id DESC LIMIT ?",
                (neuron_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_ranking(self, limit: int = 20) -> list[dict[str, Any]]:
        """Retorna ranking de neuronas por composite score."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM neuron_eval_metrics
                   ORDER BY composite_score DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_domain_stats(self, domain: str) -> dict[str, Any]:
        """Retorna estadísticas agregadas por dominio."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT
                   COUNT(*) as neuron_count,
                   AVG(composite_score) as avg_composite,
                   AVG(success_rate) as avg_success_rate,
                   AVG(avg_score) as avg_score,
                   SUM(total_activations) as total_activations
                   FROM (
                     SELECT *, CAST(successful_activations AS REAL) / MAX(total_activations, 1) as success_rate
                     FROM neuron_eval_metrics WHERE domain = ?
                   )""",
                (domain,),
            ).fetchone()
            return dict(row) if row else {}

    def get_trending(self, direction: str = "up", limit: int = 10) -> list[dict[str, Any]]:
        """Retorna neuronas con tendencia ascendente o descendente."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM neuron_eval_metrics
                   WHERE trend = ? ORDER BY composite_score DESC LIMIT ?""",
                (direction, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_stale_neuron_ids(self, max_age_hours: int = 72) -> list[int]:
        """Retorna IDs de neuronas que no se han activado recientemente."""
        cutoff = time.time() - max_age_hours * 3600
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT neuron_id FROM neuron_eval_metrics WHERE last_activation_at < ? AND last_activation_at > 0",
                (cutoff,),
            ).fetchall()
            return [r["neuron_id"] for r in rows]

    def _compute_composite(
        self,
        avg_score: float,
        ema_score: float,
        success_rate: float,
        total_activations: int,
        last_activation: float,
        first_activation: float,
        avg_response_ms: float,
    ) -> float:
        """Calcula score compuesto (0.0-1.0)."""
        score = 0.0

        score += avg_score * 0.25
        score += ema_score * 0.25
        score += success_rate * 0.20

        if total_activations >= 10:
            score += 0.10
        elif total_activations >= 5:
            score += 0.05

        hours_active = (last_activation - first_activation) / 3600
        if hours_active > 24:
            score += 0.10
        elif hours_active > 6:
            score += 0.05

        if avg_response_ms > 0 and avg_response_ms < 5000:
            score += 0.10
        elif avg_response_ms > 0 and avg_response_ms < 15000:
            score += 0.05

        return round(min(1.0, max(0.0, score)), 4)

    def _compute_trend(self, current_ema: float, previous_ema: float) -> str:
        """Calcula tendencia basada en cambio de EMA."""
        diff = current_ema - previous_ema
        if diff > 0.05:
            return "up"
        elif diff < -0.05:
            return "down"
        return "stable"
