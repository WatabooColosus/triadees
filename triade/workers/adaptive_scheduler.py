"""Adaptive Scheduler · ajusta intervalos de tareas basado en historial.

Analiza duración, tasa de éxito y carga del sistema para optimizar
cuándo ejecutar cada tipo de tarea. Evita sobrecarga y mejora eficiencia.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

_HISTORY_TABLE = """
CREATE TABLE IF NOT EXISTS scheduler_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    run_ref TEXT,
    started_at REAL NOT NULL,
    finished_at REAL,
    duration_ms REAL,
    success INTEGER DEFAULT 1,
    resource_score REAL DEFAULT 0.5,
    interval_recommended REAL DEFAULT 60.0
);
"""

_METRICS_TABLE = """
CREATE TABLE IF NOT EXISTS scheduler_metrics (
    task_type TEXT PRIMARY KEY,
    avg_duration_ms REAL DEFAULT 0.0,
    success_rate REAL DEFAULT 1.0,
    last_run_at REAL DEFAULT 0.0,
    avg_interval_ms REAL DEFAULT 60000.0,
    ema_duration_ms REAL DEFAULT 0.0,
    ema_success REAL DEFAULT 1.0,
    sample_count INTEGER DEFAULT 0,
    updated_at REAL NOT NULL
);
"""


class AdaptiveScheduler:
    """Planificador que ajusta intervalos según rendimiento histórico."""

    DEFAULT_INTERVALS: dict[str, float] = {
        "pulse_check": 30.0,
        "pending_learning_review": 120.0,
        "semantic_memory_governance": 180.0,
        "neuron_candidate_formation": 300.0,
        "experimental_neuron_activity": 240.0,
        "neuron_autopromotion": 360.0,
        "federation_inbox_review": 120.0,
        "memory_consolidation_review": 300.0,
        "stable_consolidation_review": 600.0,
        "system_debt_scan": 600.0,
        "bodega_global_review": 180.0,
    }

    EMA_ALPHA = 0.3
    MIN_INTERVAL = 10.0
    MAX_INTERVAL = 3600.0

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute(_HISTORY_TABLE)
            conn.execute(_METRICS_TABLE)

    def record_task_execution(
        self,
        task_type: str,
        duration_ms: float,
        success: bool,
        run_ref: str | None = None,
        resource_score: float = 0.5,
    ) -> None:
        """Registra una ejecución y actualiza métricas."""
        now = time.time()
        recommended = self._compute_interval(task_type, duration_ms, success, resource_score)

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO scheduler_history
                   (task_type, run_ref, started_at, finished_at, duration_ms, success, resource_score, interval_recommended)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_type, run_ref, now - duration_ms / 1000, now, duration_ms, 1 if success else 0, resource_score, recommended),
            )

            row = conn.execute(
                "SELECT * FROM scheduler_metrics WHERE task_type = ?", (task_type,)
            ).fetchone()

            if row is None:
                conn.execute(
                    """INSERT INTO scheduler_metrics
                       (task_type, avg_duration_ms, success_rate, last_run_at, avg_interval_ms,
                        ema_duration_ms, ema_success, sample_count, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                    (task_type, duration_ms, 1.0 if success else 0.0, now, recommended, duration_ms, 1.0 if success else 0.0, now),
                )
            else:
                alpha = self.EMA_ALPHA
                new_ema_dur = alpha * duration_ms + (1 - alpha) * row["ema_duration_ms"]
                new_ema_succ = alpha * (1.0 if success else 0.0) + (1 - alpha) * row["ema_success"]
                new_avg_interval = alpha * recommended + (1 - alpha) * row["avg_interval_ms"]
                new_sample = row["sample_count"] + 1

                conn.execute(
                    """UPDATE scheduler_metrics SET
                       avg_duration_ms = ?,
                       success_rate = ?,
                       last_run_at = ?,
                       avg_interval_ms = ?,
                       ema_duration_ms = ?,
                       ema_success = ?,
                       sample_count = ?,
                       updated_at = ?
                       WHERE task_type = ?""",
                    (duration_ms, 1.0 if success else 0.0, now, new_avg_interval,
                     new_ema_dur, new_ema_succ, new_sample, now, task_type),
                )

    def get_recommended_interval(self, task_type: str) -> float:
        """Retorna el intervalo recomendado para un tipo de tarea."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT avg_interval_ms FROM scheduler_metrics WHERE task_type = ?",
                (task_type,),
            ).fetchone()
            if row:
                return max(self.MIN_INTERVAL, min(row["avg_interval_ms"], self.MAX_INTERVAL))
        return self.DEFAULT_INTERVALS.get(task_type, 60.0)

    def should_skip_task(self, task_type: str) -> bool:
        """Determina si una tarea debe saltarse por haberse ejecutado recientemente."""
        interval = self.get_recommended_interval(task_type)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_run_at FROM scheduler_metrics WHERE task_type = ?",
                (task_type,),
            ).fetchone()
            if row and row["last_run_at"]:
                elapsed = time.time() - row["last_run_at"]
                return elapsed < interval * 0.5
        return False

    def get_task_priority(self, task_type: str) -> float:
        """Calcula prioridad dinámica (0.0-1.0) basada en urgencia y rendimiento."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT success_rate, sample_count, last_run_at FROM scheduler_metrics WHERE task_type = ?",
                (task_type,),
            ).fetchone()
            if not row or row["sample_count"] < 3:
                return 0.5

            base_priority = 1.0 - row["success_rate"]
            staleness = time.time() - row["last_run_at"] if row["last_run_at"] else 0
            staleness_bonus = min(1.0, staleness / 3600)
            return round(min(1.0, base_priority * 0.4 + staleness_bonus * 0.6), 3)

    def get_all_metrics(self) -> dict[str, Any]:
        """Retorna métricas de todos los tipos de tarea."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM scheduler_metrics ORDER BY task_type").fetchall()
            return {row["task_type"]: dict(row) for row in rows}

    def _compute_interval(
        self,
        task_type: str,
        duration_ms: float,
        success: bool,
        resource_score: float,
    ) -> float:
        """Calcula intervalo recomendado."""
        base = self.DEFAULT_INTERVALS.get(task_type, 60.0)

        duration_factor = 1.0
        if duration_ms > 30000:
            duration_factor = 1.5
        elif duration_ms > 10000:
            duration_factor = 1.2
        elif duration_ms < 1000:
            duration_factor = 0.8

        success_factor = 1.0
        if not success:
            success_factor = 1.3
        elif duration_ms < 500:
            success_factor = 0.9

        resource_factor = 1.0 + (resource_score - 0.5) * 0.4

        return max(self.MIN_INTERVAL, min(base * duration_factor * success_factor * resource_factor, self.MAX_INTERVAL))

    def cleanup_old_history(self, max_age_days: int = 30) -> int:
        """Limpia historial antiguo."""
        cutoff = time.time() - max_age_days * 86400
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM scheduler_history WHERE started_at < ?", (cutoff,))
            return cursor.rowcount
