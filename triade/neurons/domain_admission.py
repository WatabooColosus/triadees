"""Turn a verified routing gap into a governed, persistent formation proposal.

Admission is not activation. Existing education events retain the request and
Creadora/Formativa produce a candidate contract without claiming competence.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from triade.core.neuron_formation_pipeline import form_candidate
from triade.neurons.competency_store import utc_now
from triade.neurons.learning_router import NeuralLearningRouter, _tokens


class DomainAdmissionCoordinator:
    def __init__(self, db_path: str | Path) -> None:
        self.router = NeuralLearningRouter(db_path)

    def request(self, candidate_id: str, *, correlation_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", correlation_id):
            raise ValueError("invalid_admission_correlation_id")
        candidate = self.router._verified_candidate(candidate_id)
        domain = str(candidate["domain"] or "")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", domain):
            raise ValueError("invalid_neuron_domain")
        try:
            neuron, contract = self.router._select_neuron(candidate)
        except ValueError as exc:
            if str(exc) != "no_compatible_neuron":
                raise
        else:
            return {
                "status": "existing_competence_available",
                "neuron_id": int(neuron["id"]),
                "contract": contract.to_dict(),
                "correlation_id": correlation_id,
                "candidate_id": candidate_id,
            }

        # Compare domains separately from the router's current decision. A
        # nearby neuron is a training target, not automatically compatible.
        with self.router._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                """SELECT id,payload_json FROM neuron_education_events
                WHERE event_type='domain_admission_requested'
                  AND json_extract(payload_json,'$.candidate_id')=?
                ORDER BY id DESC LIMIT 1""",
                (candidate_id,),
            ).fetchone()
            if previous is not None:
                result = json.loads(previous["payload_json"])
                return {**result, "event_id": int(previous["id"])}
            rows = conn.execute(
                """SELECT id,domain,contract_json FROM neurons
                WHERE status IN ('experimental','active','stable') ORDER BY id"""
            ).fetchall()
            ranked: list[tuple[int, int]] = []
            for row in rows:
                overlap = len(_tokens(domain.replace("_", " ")) &
                              _tokens(str(row["domain"]).replace("_", " ")))
                if overlap:
                    ranked.append((overlap, int(row["id"])))
            parent = max(ranked, key=lambda item: (item[0], -item[1]))[1] if ranked else None
            decision = "EXTEND_EXISTING_NEURON" if parent is not None else "CREATE_NEW_NEURON"
            request_id = "admission-" + hashlib.sha256(candidate_id.encode()).hexdigest()[:24]
            evidence = conn.execute(
                """SELECT id,artifact_ref FROM learning_evidence
                WHERE candidate_id=? AND decision='improved'
                ORDER BY updated_at DESC LIMIT 1""", (candidate_id,),
            ).fetchone()
            formed = form_candidate({
                "name": request_id,
                "mission": f"Evaluar y aplicar conocimiento verificable del dominio {domain} en tareas posteriores distintas, midiendo errores y regresiones.",
                "domain": domain,
                "source": "verified_learning_domain_need",
            })
            # These are design requirements, not fabricated training results.
            result = {
                "request_id": request_id,
                "candidate_id": candidate_id,
                "correlation_id": correlation_id,
                "domain": domain,
                "required_capability": "verified_knowledge_application",
                "source_mission": str(candidate["source_ref"] or ""),
                "risk": str(candidate["risk_level"] or "low"),
                "confidence": float(candidate["confidence"] or 0),
                "evidence_refs": [f"sqlite:learning_evidence:{evidence['id']}", str(evidence["artifact_ref"] or "")],
                "decision": decision,
                "parent_neuron_id": parent,
                "status": "awaiting_held_out_certification",
                "creator_spec": formed["creator_spec"],
                "specification_review": formed["training_result"],
                "competence_certified": False,
                "allowed_actions": ["observe", "propose"],
                "curriculum_requirements": {
                    "separate_training_and_held_out": True,
                    "metrics": ["success_rate", "errors", "latency", "resource_usage"],
                    "requires_independent_evaluation": True,
                    "requires_regression_gate": True,
                },
                "activated": False,
                "stable_memory_written": False,
                "created_at": utc_now(),
            }
            cursor = conn.execute(
                """INSERT INTO neuron_education_events
                (session_id,neuron_id,event_type,payload_json,created_at)
                VALUES(NULL,NULL,'domain_admission_requested',?,?)""",
                (json.dumps(result, ensure_ascii=False), result["created_at"]),
            )
            return {**result, "event_id": int(cursor.lastrowid)}
