"""Turn a verified routing gap into a governed, persistent formation proposal.

Admission is not activation. Existing education events retain the request and
Creadora/Formativa produce a candidate contract without claiming competence.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from triade.core.neuron_formation_pipeline import form_candidate
from triade.neurons.competency_store import utc_now
from triade.neurons.learning_router import NeuralLearningRouter, _tokens

ADMISSION_SCHEMA_VERSION = 2
REQUIRED_SPEC_FIELDS = (
    "name", "mission", "domain", "triggers", "inputs_allowed", "outputs_allowed",
    "forbidden_actions", "success_metrics", "evidence_required", "risk_level",
    "resource_profile", "training_requirements", "certification_requirements",
)


def require_complete_specification(spec: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_SPEC_FIELDS if not spec.get(field)]
    if missing:
        raise ValueError("SPEC_INCOMPLETE:" + ",".join(missing))


def _reusable(result: dict[str, Any], *, domain: str, correlation_id: str,
              required_capability: str) -> bool:
    try:
        require_complete_specification(result.get("creator_spec") or {})
        created = datetime.fromisoformat(result["created_at"].replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - created
    except (ValueError, TypeError, KeyError, AttributeError):
        return False
    return (
        result.get("schema_version") == ADMISSION_SCHEMA_VERSION
        and result.get("domain") == domain
        and result["creator_spec"]["domain"] == domain
        and result.get("required_capability") == required_capability
        and result.get("correlation_id") == correlation_id
        and result.get("creator_spec", {}).get("correlation_id") == correlation_id
        and result.get("status") == "awaiting_held_out_certification"
        and not result.get("activated")
        and timedelta(0) <= age <= timedelta(days=7)
    )


class DomainAdmissionCoordinator:
    def __init__(self, db_path: str | Path) -> None:
        self.router = NeuralLearningRouter(db_path)

    def form(self, event_id: int, *, correlation_id: str) -> dict[str, Any]:
        """Persist a valid Creadora proposal as CANDIDATE, never as competence."""
        from triade.core.neuron_creator import NeuronSpec
        from triade.core.neuron_registry import NeuronRegistry

        with self.router._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM neuron_education_events WHERE id=? AND event_type='domain_admission_requested'",
                (event_id,),
            ).fetchone()
        if row is None:
            raise ValueError("admission_not_found")
        admission = json.loads(row["payload_json"])
        if not _reusable(admission, domain=admission["domain"], correlation_id=correlation_id,
                         required_capability=admission["required_capability"]):
            raise ValueError("SPEC_INCOMPLETE_OR_INVALID_LINEAGE")
        self.router._verified_candidate(admission["candidate_id"])
        spec = admission["creator_spec"]
        # Extensions require independent certification too. Never mutate the
        # parent's contract on the strength of a semantic proposal alone.
        if admission["decision"] == "EXTEND_EXISTING_NEURON":
            return {"status": "blocked", "reason": "extension_requires_held_out_evidence",
                    "correlation_id": correlation_id, "admission_event_id": event_id}
        registry = NeuronRegistry(self.router.db_path)
        candidate_spec = NeuronSpec(**{
            key: value for key, value in spec.items() if key in NeuronSpec.__dataclass_fields__
        })
        candidate_spec.status = "candidate"
        neuron_id = registry.register(candidate_spec, contract_payload={
            **spec, "admission_event_id": event_id, "candidate_id": admission["candidate_id"],
            "correlation_id": correlation_id, "competence_certified": False,
            "activation_policy": {"default": "candidate_only", "auto_approve": False},
        }, conflict_policy="create_only")
        receipt = {"status": "candidate", "neuron_id": neuron_id,
                   "correlation_id": correlation_id, "admission_event_id": event_id,
                   "training_status": "pending_executable_curriculum",
                   "competence_certified": False, "activated": False}
        with self.router._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM neuron_education_events WHERE event_type='domain_candidate_formed' AND json_extract(payload_json,'$.admission_event_id')=?",
                (event_id,),
            ).fetchone()
            if existing is None:
                cursor = conn.execute(
                    "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(NULL,?,'domain_candidate_formed',?,?)",
                    (neuron_id, json.dumps(receipt), utc_now()),
                )
                receipt["event_id"] = int(cursor.lastrowid)
            else:
                receipt["event_id"] = int(existing["id"])
        return receipt

    def request(self, candidate_id: str, *, correlation_id: str,
                required_capability: str = "verified_knowledge_application") -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", correlation_id):
            raise ValueError("invalid_admission_correlation_id")
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,95}", required_capability):
            raise ValueError("invalid_required_capability")
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
                ORDER BY id DESC""",
                (candidate_id,),
            ).fetchall()
            for prior in previous:
                try:
                    result = json.loads(prior["payload_json"])
                except (ValueError, TypeError):
                    continue
                if isinstance(result, dict) and _reusable(
                    result, domain=domain, correlation_id=correlation_id,
                    required_capability=required_capability,
                ):
                    return {**result, "event_id": int(prior["id"])}
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
            request_id = "admission-" + hashlib.sha256(
                f"{candidate_id}:{domain}:{required_capability}:{correlation_id}:{len(previous)}".encode()
            ).hexdigest()[:24]
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
                "risk_level": str(candidate["risk_level"] or "low"),
                "inputs_allowed": ["verified_knowledge", "evidence_refs", "task_context", "verification_reports"],
                "outputs_allowed": ["knowledge_application", "execution_result", "verification_request"],
                "success_metrics": ["success_rate", "error_rate", "latency_ms", "resource_usage", "held_out_generalization"],
            })
            require_complete_specification(formed["creator_spec"])
            formed["creator_spec"]["correlation_id"] = correlation_id
            # These are design requirements, not fabricated training results.
            result = {
                "request_id": request_id,
                "schema_version": ADMISSION_SCHEMA_VERSION,
                "supersedes_event_ids": [int(row["id"]) for row in previous],
                "candidate_id": candidate_id,
                "correlation_id": correlation_id,
                "domain": domain,
                "required_capability": required_capability,
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
