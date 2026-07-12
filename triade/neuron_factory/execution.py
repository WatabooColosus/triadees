"""Ejecución determinista y auditable de candidatos dentro del sandbox."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .candidate import NeuronCandidateFactory
from .store import NeuronSpecificationStore


class SandboxExecutionEngine:
    """Ejecuta políticas declarativas; no permite código arbitrario."""

    SUPPORTED_POLICIES = {"configuration"}

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.candidates = NeuronCandidateFactory(self.db_path)
        self.specifications = NeuronSpecificationStore(self.db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS neuron_candidate_executions (
                    execution_id TEXT PRIMARY KEY,
                    candidate_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifact_json TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_neuron_candidate_execution
                    ON neuron_candidate_executions(candidate_id, created_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def execute_configuration(self, candidate_id: str, configuration: dict[str, Any]) -> dict[str, Any]:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(f"candidato no registrado: {candidate_id}")
        if candidate.get("status") != "created":
            raise ValueError("el candidato no está disponible para ejecución")
        policy = str(candidate.get("training_policy") or "")
        if policy not in self.SUPPORTED_POLICIES:
            raise ValueError(f"política no soportada: {policy}")
        if not isinstance(configuration, dict) or not configuration:
            raise ValueError("la configuración debe ser un objeto no vacío")

        budget = candidate["resource_budget"]
        payload = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
        max_bytes = int(budget["max_storage_mb"]) * 1024 * 1024
        if len(payload) > max_bytes:
            raise ValueError("la configuración excede el presupuesto de almacenamiento")

        started = time.perf_counter()
        artifact = {
            "execution_id": f"execution-{uuid.uuid4().hex}",
            "candidate_id": candidate_id,
            "sandbox_id": candidate["sandbox_id"],
            "policy": policy,
            "configuration": json.loads(payload.decode("utf-8")),
            "status": "completed",
        }
        canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":"))
        artifact["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        artifact["duration_ms"] = duration_ms

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO neuron_candidate_executions
                (execution_id, candidate_id, status, artifact_json, duration_ms)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    artifact["execution_id"],
                    candidate_id,
                    artifact["status"],
                    json.dumps(artifact, sort_keys=True),
                    duration_ms,
                ),
            )
            updated_candidate = dict(candidate)
            updated_candidate["status"] = "executed"
            updated_candidate["execution_id"] = artifact["execution_id"]
            updated_candidate["execution_sha256"] = artifact["sha256"]
            conn.execute(
                """UPDATE neuron_candidates
                SET status = ?, manifest_json = ?
                WHERE candidate_id = ?""",
                ("executed", json.dumps(updated_candidate, sort_keys=True), candidate_id),
            )

        self.specifications.transition(candidate["neuron_id"], candidate["version"], "evaluated")
        return artifact

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT artifact_json FROM neuron_candidate_executions WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        return json.loads(row["artifact_json"]) if row else None

    def list_for_candidate(self, candidate_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT artifact_json FROM neuron_candidate_executions
                WHERE candidate_id = ? ORDER BY created_at, execution_id""",
                (candidate_id,),
            ).fetchall()
        return [json.loads(row["artifact_json"]) for row in rows]
