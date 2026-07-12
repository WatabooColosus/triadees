"""Cierre operacional del ciclo de vida de neuronas promovidas."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from triade.capabilities import CapabilityDefinition, CapabilityRegistry

from .candidate import NeuronCandidateFactory
from .store import NeuronSpecificationStore


class NeuronLifecycleManager:
    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)
        self.candidates = NeuronCandidateFactory(self.db_path)
        self.specifications = NeuronSpecificationStore(self.db_path)
        self.capabilities = CapabilityRegistry(self.db_path)

    def register_demonstrated_capabilities(self, candidate_id: str) -> list[dict[str, Any]]:
        manifest = self.candidates.get(candidate_id)
        if manifest is None:
            raise KeyError(f"candidato no registrado: {candidate_id}")
        if manifest.get("status") != "promoted":
            raise ValueError("solo un candidato promovido puede registrar capacidades")
        specification = self.specifications.get(manifest["neuron_id"], manifest["version"])
        if specification is None or specification.get("state") != "promoted":
            raise ValueError("la especificación no está promovida")

        registered: list[dict[str, Any]] = []
        for capability_id in specification.get("provides_capabilities", []):
            existing = self.capabilities.get(capability_id, specification["version"])
            if existing is not None:
                registered.append(existing)
                continue
            definition = CapabilityDefinition(
                capability_id=capability_id,
                name=capability_id.replace("_", " ").title(),
                domain=specification["domain"],
                version=specification["version"],
                owner=specification["owner"],
                component=specification["component"],
                state="active",
                critical=bool(specification.get("critical")),
                dependencies=tuple(specification.get("requires_capabilities", [])),
                evaluation_suites=tuple(specification.get("evaluation_suites", [])),
                rollback_policy=specification.get("rollback_policy"),
                input_contract=specification["input_contract"],
                output_contract=specification["output_contract"],
                permissions=("read", "execute"),
            )
            registered.append(self.capabilities.register(definition))
        return registered

    def rollback(self, candidate_id: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("reason es obligatorio")
        manifest = self.candidates.get(candidate_id)
        if manifest is None:
            raise KeyError(f"candidato no registrado: {candidate_id}")
        if manifest.get("status") != "promoted":
            raise ValueError("solo un candidato promovido puede revertirse")
        specification = self.specifications.get(manifest["neuron_id"], manifest["version"])
        if specification is None or specification.get("state") != "promoted":
            raise ValueError("la especificación no está promovida")

        for capability_id in specification.get("provides_capabilities", []):
            capability = self.capabilities.get(capability_id, specification["version"])
            if capability is not None:
                self.capabilities.set_state(capability_id, specification["version"], "blocked")
        quarantined = self.specifications.transition(
            manifest["neuron_id"], manifest["version"], "quarantined"
        )
        updated = dict(manifest)
        updated["status"] = "rolled_back"
        updated["rollback_reason"] = reason.strip()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE neuron_candidates SET status = ?, manifest_json = ? WHERE candidate_id = ?",
                ("rolled_back", json.dumps(updated, sort_keys=True), candidate_id),
            )
        return {"candidate_id": candidate_id, "status": "rolled_back", "specification": quarantined}

    def snapshot(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            candidate_rows = conn.execute(
                "SELECT status, COUNT(*) AS total FROM neuron_candidates GROUP BY status"
            ).fetchall()
            specification_rows = conn.execute(
                "SELECT state, COUNT(*) AS total FROM neuron_specifications GROUP BY state"
            ).fetchall()
            executions = conn.execute(
                "SELECT COUNT(*) AS total FROM neuron_candidate_executions"
            ).fetchone()["total"]
        return {
            "candidates": {row["status"]: row["total"] for row in candidate_rows},
            "specifications": {row["state"]: row["total"] for row in specification_rows},
            "executions": executions,
        }
