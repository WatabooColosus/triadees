"""Puente controlado entre propuestas de mejora y Neuron Factory."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from triade.neuron_factory import NeuronCandidateFactory, NeuronSpecificationStore


@dataclass(frozen=True, slots=True)
class ImprovementBudget:
    max_active_candidates: int = 2
    max_memory_mb: int = 4096
    max_runtime_seconds: int = 1800
    max_storage_mb: int = 512

    def validate(self) -> None:
        values = (
            self.max_active_candidates,
            self.max_memory_mb,
            self.max_runtime_seconds,
            self.max_storage_mb,
        )
        if any(value < 1 for value in values):
            raise ValueError("todos los límites globales deben ser positivos")


class ImprovementNeuronFactoryBridge:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        budget: ImprovementBudget | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.budget = budget or ImprovementBudget()
        self.budget.validate()
        self.candidates = NeuronCandidateFactory(self.db_path)
        self.specifications = NeuronSpecificationStore(self.db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS improvement_candidate_links (
                    proposal_id TEXT NOT NULL,
                    candidate_id TEXT PRIMARY KEY,
                    neuron_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resource_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(proposal_id, candidate_id)
                );
                CREATE INDEX IF NOT EXISTS idx_improvement_candidate_links_status
                    ON improvement_candidate_links(status, created_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def approve(self, proposal_id: str, *, approved_by: str) -> dict[str, Any]:
        if not approved_by.strip():
            raise ValueError("approved_by es obligatorio")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, status FROM improvement_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"propuesta no registrada: {proposal_id}")
            if row["status"] != "open":
                raise ValueError("solo una propuesta abierta puede aprobarse")
            payload = json.loads(row["payload_json"])
            payload["approved_by"] = approved_by.strip()
            payload["approved"] = True
            conn.execute(
                "UPDATE improvement_proposals SET status = 'approved', payload_json = ? WHERE proposal_id = ?",
                (json.dumps(payload, sort_keys=True), proposal_id),
            )
            conn.execute(
                """INSERT INTO improvement_history
                (entity_type, entity_id, action, payload_json, created_at)
                VALUES ('proposal', ?, 'approved', ?, strftime('%s','now'))""",
                (proposal_id, json.dumps(payload, sort_keys=True)),
            )
        return {**payload, "status": "approved"}

    def create_candidate(
        self,
        proposal_id: str,
        *,
        neuron_id: str,
        version: str,
    ) -> dict[str, Any]:
        proposal = self._proposal(proposal_id)
        if proposal["status"] not in {"approved", "candidate_created"}:
            raise ValueError("la propuesta debe estar aprobada antes de crear candidatos")
        specification = self.specifications.get(neuron_id, version)
        if specification is None:
            raise KeyError(f"especificación no registrada: {neuron_id}@{version}")
        if proposal["requested_capability"] not in specification.get("provides_capabilities", []):
            raise ValueError("la especificación no aporta la capacidad solicitada")

        existing = self._links_for_proposal(proposal_id)
        if len(existing) >= int(proposal["max_candidates"]):
            raise ValueError("se alcanzó el máximo de candidatos de la propuesta")

        resource = specification["resource_budget"]
        usage = self.resource_usage()
        projected = {
            "active_candidates": usage["active_candidates"] + 1,
            "memory_mb": usage["memory_mb"] + int(resource["max_memory_mb"]),
            "runtime_seconds": usage["runtime_seconds"] + int(resource["max_runtime_seconds"]),
            "storage_mb": usage["storage_mb"] + int(resource["max_storage_mb"]),
        }
        self._require_within_budget(projected)

        candidate = self.candidates.create(neuron_id, version)
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO improvement_candidate_links
                (proposal_id, candidate_id, neuron_id, version, status, resource_json)
                VALUES (?, ?, ?, ?, 'active', ?)""",
                (
                    proposal_id,
                    candidate["candidate_id"],
                    neuron_id,
                    version,
                    json.dumps(resource, sort_keys=True),
                ),
            )
            conn.execute(
                "UPDATE improvement_proposals SET status = 'candidate_created' WHERE proposal_id = ?",
                (proposal_id,),
            )
            conn.execute(
                """INSERT INTO improvement_history
                (entity_type, entity_id, action, payload_json, created_at)
                VALUES ('proposal', ?, 'candidate_created', ?, strftime('%s','now'))""",
                (proposal_id, json.dumps(candidate, sort_keys=True)),
            )
        return {
            "proposal_id": proposal_id,
            "candidate": candidate,
            "resource_usage": projected,
        }

    def release_candidate(self, candidate_id: str, *, outcome: str) -> dict[str, Any]:
        if outcome not in {"completed", "rejected", "rolled_back", "cancelled"}:
            raise ValueError("outcome inválido")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT proposal_id, status FROM improvement_candidate_links WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"candidato no vinculado: {candidate_id}")
            if row["status"] != "active":
                raise ValueError("el candidato ya fue liberado")
            conn.execute(
                "UPDATE improvement_candidate_links SET status = ? WHERE candidate_id = ?",
                (outcome, candidate_id),
            )
            remaining = conn.execute(
                """SELECT COUNT(*) AS total FROM improvement_candidate_links
                WHERE proposal_id = ? AND status = 'active'""",
                (row["proposal_id"],),
            ).fetchone()["total"]
            proposal_status = "candidate_created" if remaining else outcome
            conn.execute(
                "UPDATE improvement_proposals SET status = ? WHERE proposal_id = ?",
                (proposal_status, row["proposal_id"]),
            )
        return {
            "candidate_id": candidate_id,
            "proposal_id": row["proposal_id"],
            "status": outcome,
            "proposal_status": proposal_status,
        }

    def resource_usage(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT resource_json FROM improvement_candidate_links WHERE status = 'active'"
            ).fetchall()
        resources = [json.loads(row["resource_json"]) for row in rows]
        return {
            "active_candidates": len(resources),
            "memory_mb": sum(int(item["max_memory_mb"]) for item in resources),
            "runtime_seconds": sum(int(item["max_runtime_seconds"]) for item in resources),
            "storage_mb": sum(int(item["max_storage_mb"]) for item in resources),
        }

    def _proposal(self, proposal_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, status FROM improvement_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"propuesta no registrada: {proposal_id}")
        return {**json.loads(row["payload_json"]), "status": row["status"]}

    def _links_for_proposal(self, proposal_id: str) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT candidate_id FROM improvement_candidate_links WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchall()

    def _require_within_budget(self, projected: dict[str, int]) -> None:
        limits = {
            "active_candidates": self.budget.max_active_candidates,
            "memory_mb": self.budget.max_memory_mb,
            "runtime_seconds": self.budget.max_runtime_seconds,
            "storage_mb": self.budget.max_storage_mb,
        }
        exceeded = [name for name, value in projected.items() if value > limits[name]]
        if exceeded:
            raise ValueError(f"presupuesto global excedido: {', '.join(sorted(exceeded))}")
