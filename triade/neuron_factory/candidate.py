"""Creación controlada de candidatos de neurona en sandbox."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from triade.capabilities import CapabilityRegistry

from .store import NeuronSpecificationStore


@dataclass(frozen=True, slots=True)
class NeuronCandidate:
    candidate_id: str
    neuron_id: str
    version: str
    sandbox_id: str
    specification_sha256: str
    status: str = "created"

    def to_dict(self) -> dict[str, str]:
        return {
            "candidate_id": self.candidate_id,
            "neuron_id": self.neuron_id,
            "version": self.version,
            "sandbox_id": self.sandbox_id,
            "specification_sha256": self.specification_sha256,
            "status": self.status,
        }


class NeuronCandidateFactory:
    """Valida especificaciones y genera candidatos aislados y auditables."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.specifications = NeuronSpecificationStore(self.db_path)
        self.capabilities = CapabilityRegistry(self.db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS neuron_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    neuron_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    sandbox_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_neuron_candidates_neuron
                    ON neuron_candidates(neuron_id, version, created_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, neuron_id: str, version: str) -> dict[str, Any]:
        specification = self.specifications.get(neuron_id, version)
        if specification is None:
            raise KeyError(f"especificación no registrada: {neuron_id}@{version}")
        if specification["state"] != "specified":
            raise ValueError("la especificación debe estar en estado specified")
        if not specification.get("sandbox_required", False):
            raise ValueError("la especificación no exige sandbox")

        missing = [
            capability_id
            for capability_id in specification.get("requires_capabilities", [])
            if self.capabilities.get(capability_id) is None
        ]
        if missing:
            raise ValueError(f"capacidades requeridas inexistentes: {', '.join(sorted(missing))}")

        blocked = []
        for capability_id in specification.get("requires_capabilities", []):
            capability = self.capabilities.get(capability_id)
            if capability and capability.get("state") == "blocked":
                blocked.append(capability_id)
        if blocked:
            raise ValueError(f"capacidades requeridas bloqueadas: {', '.join(sorted(blocked))}")

        exported = self.specifications.export(neuron_id, version)
        candidate = NeuronCandidate(
            candidate_id=f"candidate-{uuid.uuid4().hex}",
            neuron_id=neuron_id,
            version=version,
            sandbox_id=f"sandbox-{uuid.uuid4().hex}",
            specification_sha256=str(exported["sha256"]),
        )
        manifest = {
            **candidate.to_dict(),
            "resource_budget": specification["resource_budget"],
            "training_policy": specification["training_policy"],
            "required_capabilities": specification.get("requires_capabilities", []),
            "provided_capabilities": specification.get("provides_capabilities", []),
        }
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
        manifest["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO neuron_candidates
                (candidate_id, neuron_id, version, sandbox_id, status, manifest_json)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    candidate.candidate_id,
                    candidate.neuron_id,
                    candidate.version,
                    candidate.sandbox_id,
                    candidate.status,
                    json.dumps(manifest, sort_keys=True),
                ),
            )
        self.specifications.transition(neuron_id, version, "training")
        return manifest

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT manifest_json FROM neuron_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return json.loads(row["manifest_json"]) if row else None

    def list_for_neuron(self, neuron_id: str, version: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT manifest_json FROM neuron_candidates WHERE neuron_id = ?"
        params: list[Any] = [neuron_id]
        if version:
            sql += " AND version = ?"
            params.append(version)
        sql += " ORDER BY created_at, candidate_id"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [json.loads(row["manifest_json"]) for row in rows]
