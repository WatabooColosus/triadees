"""Canary limitado para neuronas promovidas con rollback automático."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from triade.neuron_factory import NeuronCandidateFactory, NeuronLifecycleManager


class CanaryMonitor:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.candidates = NeuronCandidateFactory(self.db_path)
        self.lifecycle = NeuronLifecycleManager(self.db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS improvement_canaries (
                    canary_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    baseline_score REAL NOT NULL,
                    tolerance REAL NOT NULL,
                    traffic_percent INTEGER NOT NULL,
                    min_observations INTEGER NOT NULL,
                    max_observations INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS improvement_canary_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canary_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(canary_id) REFERENCES improvement_canaries(canary_id)
                );
                CREATE INDEX IF NOT EXISTS idx_canary_observations
                    ON improvement_canary_observations(canary_id, id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def start(
        self,
        candidate_id: str,
        *,
        baseline_score: float,
        tolerance: float = 0.02,
        traffic_percent: int = 10,
        min_observations: int = 3,
        max_observations: int = 10,
    ) -> dict[str, Any]:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(f"candidato no registrado: {candidate_id}")
        if candidate.get("status") != "promoted":
            raise ValueError("solo un candidato promovido puede iniciar canary")
        if not 0 <= baseline_score <= 1:
            raise ValueError("baseline_score debe estar entre 0 y 1")
        if not 0 <= tolerance < 1:
            raise ValueError("tolerance debe estar entre 0 y 1")
        if not 1 <= traffic_percent <= 25:
            raise ValueError("traffic_percent debe estar entre 1 y 25")
        if min_observations < 1 or max_observations < min_observations:
            raise ValueError("ventana de observación inválida")

        now = time.time()
        payload = {
            "canary_id": f"canary-{uuid.uuid4().hex}",
            "candidate_id": candidate_id,
            "status": "running",
            "baseline_score": baseline_score,
            "tolerance": tolerance,
            "traffic_percent": traffic_percent,
            "min_observations": min_observations,
            "max_observations": max_observations,
            "observation_count": 0,
        }
        with self._connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO improvement_canaries
                    (canary_id, candidate_id, status, baseline_score, tolerance,
                     traffic_percent, min_observations, max_observations,
                     payload_json, created_at, updated_at)
                    VALUES (?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        payload["canary_id"], candidate_id, baseline_score, tolerance,
                        traffic_percent, min_observations, max_observations,
                        json.dumps(payload, sort_keys=True), now, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("el candidato ya tiene un canary") from exc
        return payload

    def observe(
        self,
        canary_id: str,
        *,
        score: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not 0 <= score <= 1:
            raise ValueError("score debe estar entre 0 y 1")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM improvement_canaries WHERE canary_id = ?",
                (canary_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"canary no registrado: {canary_id}")
            if row["status"] != "running":
                raise ValueError("el canary ya terminó")
            now = time.time()
            conn.execute(
                """INSERT INTO improvement_canary_observations
                (canary_id, score, metadata_json, created_at)
                VALUES (?, ?, ?, ?)""",
                (canary_id, score, json.dumps(metadata or {}, sort_keys=True), now),
            )
            scores = [
                float(item["score"])
                for item in conn.execute(
                    "SELECT score FROM improvement_canary_observations WHERE canary_id = ? ORDER BY id",
                    (canary_id,),
                ).fetchall()
            ]

        average = sum(scores) / len(scores)
        lower_bound = float(row["baseline_score"]) - float(row["tolerance"])
        status = "running"
        rollback = None
        if len(scores) >= int(row["min_observations"]) and average < lower_bound:
            status = "rolled_back"
            rollback = self.lifecycle.rollback(
                str(row["candidate_id"]),
                f"canary degradado: average={average:.6f}, lower_bound={lower_bound:.6f}",
            )
        elif len(scores) >= int(row["max_observations"]):
            status = "graduated"

        payload = {
            "canary_id": canary_id,
            "candidate_id": row["candidate_id"],
            "status": status,
            "baseline_score": float(row["baseline_score"]),
            "tolerance": float(row["tolerance"]),
            "traffic_percent": int(row["traffic_percent"]),
            "min_observations": int(row["min_observations"]),
            "max_observations": int(row["max_observations"]),
            "observation_count": len(scores),
            "average_score": average,
            "lower_bound": lower_bound,
            "rollback": rollback,
        }
        with self._connect() as conn:
            conn.execute(
                """UPDATE improvement_canaries
                SET status = ?, payload_json = ?, updated_at = ?
                WHERE canary_id = ?""",
                (status, json.dumps(payload, sort_keys=True), time.time(), canary_id),
            )
        return payload

    def get(self, canary_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM improvement_canaries WHERE canary_id = ?",
                (canary_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None
