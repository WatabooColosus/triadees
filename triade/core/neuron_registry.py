"""Registro persistente de neuronas · Tríade Ω 1.2C.

Usa las tablas existentes `neurons` y `neuron_training` para convertir
NeuronSpec y NeuronTrainingResult en estado persistente SQLite.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .neuron_creator import NeuronSpec
from .neuron_trainer import NeuronTrainingResult


class NeuronRegistry:
    """Persistencia y consulta de neuronas internas."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.schema_path = Path("triade/memory/schemas.sql")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        if not self.schema_path.exists():
            raise FileNotFoundError(f"No existe el esquema de memoria: {self.schema_path}")
        with self._connect() as conn:
            conn.executescript(self.schema_path.read_text(encoding="utf-8"))

    def register(self, spec: NeuronSpec) -> int:
        """Crea o actualiza una neurona por nombre."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO neurons (name, mission, domain, rules, status, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    mission = excluded.mission,
                    domain = excluded.domain,
                    rules = excluded.rules,
                    status = excluded.status,
                    created_by = excluded.created_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    spec.name,
                    spec.mission,
                    spec.domain,
                    json.dumps(spec.rules, ensure_ascii=False),
                    spec.status,
                    spec.created_by,
                ),
            )
            if cursor.lastrowid:
                return int(cursor.lastrowid)
            row = conn.execute("SELECT id FROM neurons WHERE name = ?", (spec.name,)).fetchone()
            return int(row["id"])

    def store_training(self, neuron_id: int, result: NeuronTrainingResult) -> int:
        """Guarda evaluación formativa de una neurona."""
        payload = {
            "strengths": result.strengths,
            "warnings": result.warnings,
            "recommendations": result.recommendations,
        }
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO neuron_training (neuron_id, training_data, evaluation_notes, score, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    neuron_id,
                    json.dumps(result.to_dict(), ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False),
                    result.score,
                    result.status,
                ),
            )
            conn.execute(
                """
                UPDATE neurons
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (result.status, neuron_id),
            )
            return int(cursor.lastrowid)

    def update_status(self, name: str, status: str) -> dict[str, Any]:
        """Actualiza el estado de una neurona por nombre.

        Estados esperados: candidate, experimental, stable, rejected,
        needs_changes. La política de seguridad se aplica fuera de este método.
        """
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE neurons
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE name = ?
                """,
                (status, name),
            )
            row = conn.execute(
                """
                SELECT id, name, mission, domain, rules, status, created_by, created_at, updated_at
                FROM neurons
                WHERE name = ?
                """,
                (name,),
            ).fetchone()

        if row is None:
            raise KeyError(f"No existe neurona registrada: {name}")
        return self._decode_neuron(dict(row))

    def list_neurons(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, mission, domain, rules, status, created_by, created_at, updated_at
                FROM neurons
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._decode_neuron(dict(row)) for row in rows]

    def get_neuron(self, name: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, name, mission, domain, rules, status, created_by, created_at, updated_at
                FROM neurons
                WHERE name = ?
                """,
                (name,),
            ).fetchone()
        return self._decode_neuron(dict(row)) if row else None

    def list_training(self, neuron_id: int, limit: int = 10) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, neuron_id, training_data, evaluation_notes, score, status, created_at
                FROM neuron_training
                WHERE neuron_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (neuron_id, limit),
            ).fetchall()
        return [self._decode_training(dict(row)) for row in rows]

    @staticmethod
    def _decode_neuron(row: dict[str, Any]) -> dict[str, Any]:
        try:
            row["rules"] = json.loads(row.get("rules") or "[]")
        except json.JSONDecodeError:
            row["rules"] = []
        return row

    @staticmethod
    def _decode_training(row: dict[str, Any]) -> dict[str, Any]:
        for key in ["training_data", "evaluation_notes"]:
            try:
                row[key] = json.loads(row.get(key) or "{}")
            except json.JSONDecodeError:
                row[key] = {}
        return row
