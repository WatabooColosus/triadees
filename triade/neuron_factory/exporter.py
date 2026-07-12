"""Exportación determinista del ciclo completo de una neurona."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.capabilities import CapabilityRegistry
from triade.learning.evidence_bridge import LearningEvidenceBridge

from .candidate import NeuronCandidateFactory
from .store import NeuronSpecificationStore


class NeuronLifecycleExporter:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.candidates = NeuronCandidateFactory(self.db_path)
        self.specifications = NeuronSpecificationStore(self.db_path)
        self.capabilities = CapabilityRegistry(self.db_path)
        self.evidence = LearningEvidenceBridge(self.db_path)

    def export(self, candidate_id: str) -> dict[str, Any]:
        candidate = self.candidates.get(candidate_id)
        if candidate is None:
            raise KeyError(f"candidato no registrado: {candidate_id}")
        specification = self.specifications.get(candidate["neuron_id"], candidate["version"])
        if specification is None:
            raise KeyError("especificación no encontrada")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            executions = [
                json.loads(row["artifact_json"])
                for row in conn.execute(
                    """SELECT artifact_json FROM neuron_candidate_executions
                    WHERE candidate_id = ? ORDER BY created_at, execution_id""",
                    (candidate_id,),
                ).fetchall()
            ]
        capabilities = [
            item
            for capability_id in specification.get("provides_capabilities", [])
            if (item := self.capabilities.get(capability_id, specification["version"])) is not None
        ]
        document = {
            "schema_version": "1.0.0",
            "candidate": candidate,
            "specification": specification,
            "specification_history": self.specifications.history(
                specification["neuron_id"], specification["version"]
            ),
            "executions": executions,
            "evidence": self.evidence.get(candidate_id),
            "capabilities": capabilities,
        }
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
        document["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return document
