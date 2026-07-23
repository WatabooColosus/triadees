"""Orchestrator Coordination — Evita trabajo duplicado entre Supervisor, Workers y LifePulse.

Tres subsistemas independientes intentan ejecutar las mismas misiones,
learning evaluations y neuron operations contra la misma base SQLite.
Este módulo provee un lock de coordinación basado en SQLite con TTL
para garantizar que solo un subsistema ejecuta cada tipo de operación.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_LOCK_TABLE = """
CREATE TABLE IF NOT EXISTS orchestrator_locks (
    lock_key TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    acquired_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
"""


def _ensure_table(db_path: str | Path) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_LOCK_TABLE)


class CoordinationLock:
    """Lock distribuido con TTL para coordinar subsistemas.

    Usa SQLite como store. Si el lock expiró, cualquier subsistema puede
    tomarlo. Si está activo, el solicitante obtiene False.
    """

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        _ensure_table(self.db_path)

    def try_acquire(self, lock_key: str, owner: str, ttl_seconds: float = 120.0) -> bool:
        """Intenta tomar un lock. Retorna True si lo consiguió."""
        now = time.time()
        expires = now + ttl_seconds
        with sqlite3.connect(str(self.db_path)) as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT owner, expires_at FROM orchestrator_locks WHERE lock_key = ?",
                    (lock_key,),
                ).fetchone()
                if row is not None:
                    _, expired_at = row
                    if now < expired_at:
                        return False
                conn.execute(
                    "INSERT OR REPLACE INTO orchestrator_locks (lock_key, owner, acquired_at, expires_at) VALUES (?, ?, ?, ?)",
                    (lock_key, owner, now, expires),
                )
                conn.execute("COMMIT")
                return True
            except Exception:
                conn.execute("ROLLBACK")
                return False

    def release(self, lock_key: str, owner: str) -> None:
        """Libera un lock solo si el owner coincide."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "DELETE FROM orchestrator_locks WHERE lock_key = ? AND owner = ?",
                (lock_key, owner),
            )

    def cleanup_expired(self) -> int:
        """Limpia locks expirados. Retorna cuántos eliminó."""
        now = time.time()
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "DELETE FROM orchestrator_locks WHERE expires_at < ?",
                (now,),
            )
            return cursor.rowcount


# ── Coordinador global ───────────────────────────────────────────────────

class OrchestratorCoordinator:
    """Coordina las responsabilidades entre Supervisor, Workers y LifePulse.

    Reglas:
      - missions: solo WorkerBackgroundService ejecuta
      - learning: solo WorkerBackgroundService evalúa y verifica
      - neuron_candidates: solo LifePulse forma candidatos
      - neuron_promotion: solo WorkerBackgroundService auto-promueve
      - observability: cualquiera puede leer
      - memory_gap_scan: solo Supervisor escanea
    """

    LOCK_MISSIONS = "exec:missions"
    LOCK_LEARNING = "exec:learning"
    LOCK_NEURON_CANDIDATES = "exec:neuron_candidates"
    LOCK_NEURON_PROMOTION = "exec:neuron_promotion"
    LOCK_TRIADE_RUNNER = "exec:triade_runner"
    LOCK_MEMORY_GAP = "exec:memory_gap"

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.lock = CoordinationLock(db_path=db_path)
        self.db_path = db_path

    def can_execute_missions(self, owner: str, ttl: float = 120.0) -> bool:
        return self.lock.try_acquire(self.LOCK_MISSIONS, owner, ttl)

    def can_evaluate_learning(self, owner: str, ttl: float = 120.0) -> bool:
        return self.lock.try_acquire(self.LOCK_LEARNING, owner, ttl)

    def can_form_neuron_candidates(self, owner: str, ttl: float = 180.0) -> bool:
        return self.lock.try_acquire(self.LOCK_NEURON_CANDIDATES, owner, ttl)

    def can_promote_neurons(self, owner: str, ttl: float = 180.0) -> bool:
        return self.lock.try_acquire(self.LOCK_NEURON_PROMOTION, owner, ttl)

    def can_run_triade_runner(self, owner: str, ttl: float = 300.0) -> bool:
        return self.lock.try_acquire(self.LOCK_TRIADE_RUNNER, owner, ttl)

    def can_scan_memory_gaps(self, owner: str, ttl: float = 180.0) -> bool:
        return self.lock.try_acquire(self.LOCK_MEMORY_GAP, owner, ttl)

    def release(self, lock_key: str, owner: str) -> None:
        self.lock.release(lock_key, owner)

    def cleanup(self) -> int:
        return self.lock.cleanup_expired()
