"""Creación persistente de candidatos de neurona en sandbox lógico."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .specification import NeuronSpecification
from .store import NeuronSpecificationStore
from .validation import NeuronSpecificationValidator


@dataclass(frozen=True, slots=True)
class NeuronCandidate:
    candidate_id: str
    neuron_id: str
    version: str
    sandbox_ref: str
    specification_sha256: str
    state: str = "created"

    def to_dict(self) -> dict[str, str]:
        return {
            "candidate_id": self.candidate_id,
            "neuron_id": self.neuron_id,
            "version": self.version,
            "sandbox_ref": self.sandbox_ref,
            "specification_sha256": self.specification_sha256,
            "state": self.state,
        }


class NeuronCandidateFactory:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.specifications = NeuronSpecificationStore(self.db_path)
        self.validator = NeuronSpecificationValidator(self.db_path)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS neuron_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    neuron_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    sandbox_ref TEXT NOT NULL UNIQUE,
                    specification_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
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
        payload = self.specifications.get(neuron_id, version)
        if payload is None:
            raise KeyError(f"especificación no registrada: {neuron_id}@{version}")
        specification = self.specifications.from_payload(payload)
        self.validator.validate(specification).require_valid()
        if specification.state != "specified":
            raise ValueError("la especificación debe estar en estado specified")

        specification_hash = self._specification_hash(specification)
        candidate_id = uuid.uuid4().hex
        sandbox_ref = f"sandbox://neurons/{neuron_id}/{version}/{candidate_id}"
        candidate = NeuronCandidate(
            candidate_id=candidate_id,
            neuron_id=neuron_id,
            version=version,
            sandbox_ref=sandbox_ref,
            specification_sha256=specification_hash,
        )
        normalized = candidate.to_dict()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO neuron_candidates
                (candidate_id, neuron_id, version, sandbox_ref,
                 specification_sha256, state, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    candidate.candidate_id,
                    candidate.neuron_id,
                    candidate.version,
                    candidate.sandbox_ref,
                    candidate.specification_sha256,
                    candidate.state,
                    json.dumps(normalized, sort_keys=True),
                ),
            )
        self.specifications.transition(neuron_id, version, "training")
        return normalized

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM neuron_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    @staticmethod
    def _specification_hash(specification: NeuronSpecification) -> str:
        canonical = json.dumps(
            specification.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
