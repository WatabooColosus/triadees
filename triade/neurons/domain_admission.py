"""Turn a verified routing gap into a governed, persistent formation proposal.

Admission is not activation. Existing education events retain the request and
Creadora/Formativa produce a candidate contract without claiming competence.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from triade.core.neuron_formation_pipeline import form_candidate
from triade.neurons.competency_store import utc_now
from triade.neurons.learning_router import NeuralLearningRouter, _tokens


def _require_insert_id(row_id: int | None) -> int:
    if row_id is None:
        raise RuntimeError("SQLite did not return the inserted event ID")
    return row_id


ADMISSION_SCHEMA_VERSION = 2
REQUIRED_SPEC_FIELDS = (
    "name",
    "mission",
    "domain",
    "triggers",
    "inputs_allowed",
    "outputs_allowed",
    "forbidden_actions",
    "success_metrics",
    "evidence_required",
    "risk_level",
    "resource_profile",
    "training_requirements",
    "certification_requirements",
)


def require_complete_specification(spec: dict[str, Any]) -> None:
    missing = [field for field in REQUIRED_SPEC_FIELDS if not spec.get(field)]
    if missing:
        raise ValueError("SPEC_INCOMPLETE:" + ",".join(missing))
    for field in (
        "triggers",
        "inputs_allowed",
        "outputs_allowed",
        "forbidden_actions",
        "success_metrics",
        "evidence_required",
    ):
        if not isinstance(spec[field], list) or not all(
            isinstance(value, str) and value.strip() for value in spec[field]
        ):
            raise ValueError("SPEC_INCOMPLETE:" + field)
    budget = spec["resource_profile"]
    if not isinstance(budget, dict) or any(
        not isinstance(budget.get(key), (int, float)) or budget[key] <= 0
        for key in ("max_memory_mb", "max_runtime_seconds", "max_storage_mb")
    ):
        raise ValueError("SPEC_INCOMPLETE:resource_profile")
    training = spec["training_requirements"]
    certification = spec["certification_requirements"]
    if (
        not isinstance(training, dict)
        or training.get("separate_training_and_held_out") is not True
    ):
        raise ValueError("SPEC_INCOMPLETE:training_requirements")
    if (
        not isinstance(certification, dict)
        or certification.get("independent_evaluation") is not True
    ):
        raise ValueError("SPEC_INCOMPLETE:certification_requirements")


def _reusable(
    result: dict[str, Any],
    *,
    domain: str,
    correlation_id: str,
    required_capability: str,
) -> bool:
    try:
        require_complete_specification(result.get("creator_spec") or {})
        created = datetime.fromisoformat(result["created_at"])
        age = datetime.now(UTC) - created
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

    def certification_attempt(self, event_id: int) -> int | None:
        """Retry infrastructure-limited evaluation, never a failed competence gate."""
        with self.router._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM neuron_education_events WHERE event_type='domain_certification_completed' AND json_extract(payload_json,'$.admission_event_id')=? ORDER BY id DESC",
                (event_id,),
            ).fetchall()
        if not rows:
            return 1
        latest = json.loads(rows[0][0])
        if len(rows) >= 3 or latest.get("status") != "certification_failed":
            return None
        cases = [case for arm in latest.get("arms", {}).values() for case in arm]
        errors = [str(case["error"]) for case in cases if case.get("error")]
        if not errors or any(
            error not in {"timed out", "certification_resource_budget_exceeded"}
            for error in errors
        ):
            return None
        # Any measured, non-resource treatment failure is a competence failure.
        if any(
            not case.get("passed") and not case.get("error")
            for case in latest.get("arms", {}).get("treatment", [])
        ):
            return None
        return len(rows) + 1

    def train(
        self, event_id: int, *, correlation_id: str, generate: Any
    ) -> dict[str, Any]:
        """Execute Formativa's reserved curriculum, without certifying or activating.

        Receipts use the current education store and the caller is a normal
        leased worker. A successful training result is not held-out evidence.
        """
        from triade.learning.knowledge_probe import build_transfer_probe
        from triade.learning.retrieval import LearningRetriever, build_learning_block
        from triade.neurons.curriculum import admission_curriculum

        with self.router._connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM neuron_education_events WHERE id=? AND event_type='domain_admission_requested'",
                (event_id,),
            ).fetchone()
            formed = conn.execute(
                "SELECT payload_json FROM neuron_education_events WHERE event_type='domain_candidate_formed' AND json_extract(payload_json,'$.admission_event_id')=?",
                (event_id,),
            ).fetchone()
            prior = conn.execute(
                "SELECT payload_json FROM neuron_education_events WHERE event_type='domain_training_completed' AND json_extract(payload_json,'$.admission_event_id')=? ORDER BY id DESC LIMIT 1",
                (event_id,),
            ).fetchone()
        if row is None or formed is None:
            raise ValueError("formed_admission_required")
        admission, formation = json.loads(row[0]), json.loads(formed[0])
        if not _reusable(
            admission,
            domain=admission["domain"],
            correlation_id=correlation_id,
            required_capability=admission["required_capability"],
        ):
            raise ValueError("SPEC_INCOMPLETE_OR_INVALID_LINEAGE")
        if formation.get("correlation_id") != correlation_id:
            raise ValueError("formation_lineage_mismatch")
        from triade.neurons.curriculum import ADMISSION_CURRICULUM_VERSION

        if prior is not None:
            previous = json.loads(prior[0])
            # Idempotencia con reanudación solo cuando cambia el evaluador.
            # Las admisiones sin versión anterior se consideran versión 1.
            if (
                previous.get("status") != "training_blocked"
                or int(previous.get("curriculum_version", 1))
                >= ADMISSION_CURRICULUM_VERSION
            ):
                return previous
        candidate_id = admission["candidate_id"]
        self.router._verified_candidate(candidate_id)
        try:
            curriculum = admission_curriculum(
                self.router.db_path, candidate_id, admission["creator_spec"]
            )
        except ValueError as exc:
            blocked = {
                "admission_event_id": event_id,
                "neuron_id": formation["neuron_id"],
                "candidate_id": candidate_id,
                "correlation_id": correlation_id,
                "status": "training_blocked",
                "curriculum_version": ADMISSION_CURRICULUM_VERSION,
                "reason": str(exc),
                "activated": False,
                "competence_certified": False,
            }
            with self.router._connect() as conn:
                conn.execute(
                    "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(NULL,?,'domain_training_completed',?,?)",
                    (formation["neuron_id"], json.dumps(blocked), utc_now()),
                )
            return blocked
        base = {
            "admission_event_id": event_id,
            "neuron_id": formation["neuron_id"],
            "candidate_id": candidate_id,
            "correlation_id": correlation_id,
            "curriculum": curriculum,
            "curriculum_version": ADMISSION_CURRICULUM_VERSION,
            "activated": False,
            "competence_certified": False,
        }
        with self.router._connect() as conn:
            conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(NULL,?,'domain_training_started',?,?)",
                (formation["neuron_id"], json.dumps(base), utc_now()),
            )
        started = time.monotonic()
        budget = float(curriculum["resource_profile"]["max_runtime_seconds"])
        results = []
        llm_calls = 0
        rss_peak_mb = 0.0
        retriever = LearningRetriever(self.router.db_path)
        for case in curriculum["cases"]["training"]:
            import psutil

            rss_peak_mb = max(rss_peak_mb, psutil.Process().memory_info().rss / 1024**2)
            if rss_peak_mb > float(curriculum["resource_profile"]["max_memory_mb"]):
                results.append(
                    {
                        "case_id": case["case_id"],
                        "passed": False,
                        "error": "memory_budget_exceeded",
                    }
                )
                break
            remaining = budget - (time.monotonic() - started)
            if remaining <= 0:
                results.append(
                    {
                        "case_id": case["case_id"],
                        "passed": False,
                        "error": "runtime_budget_exceeded",
                    }
                )
                break
            run_id = f"{admission['request_id']}:{case['case_id']}"
            decision = retriever.retrieve_decision(
                case["question"], run_id=run_id, only_candidate_ids={candidate_id}
            )
            retriever.persist_decision(decision)
            probe = build_transfer_probe(
                self.router.db_path, candidate_id, case["input_value"]
            )
            if probe is None or probe.expected != case["reference"]:
                raise ValueError("curriculum_source_changed")
            prompt = build_learning_block(decision.matches) + "\n" + probe.question
            tick = time.monotonic()
            try:
                if candidate_id not in decision.injected_ids:
                    raise ValueError("training_knowledge_not_injected")
                llm_calls += 1
                response = generate(probe, prompt, remaining)
                passed = bool(probe.evaluator(response))
                error = None
            except (ValueError, RuntimeError, OSError) as exc:
                response, passed, error = "", False, str(exc)
            results.append(
                {
                    "case_id": case["case_id"],
                    "run_id": run_id,
                    "response": response,
                    "passed": passed,
                    "error": error,
                    "injected_ids": decision.injected_ids,
                    "latency_seconds": time.monotonic() - tick,
                }
            )
        success = len(results) == len(curriculum["cases"]["training"]) and all(
            x["passed"] for x in results
        )
        outcome = {
            **base,
            "status": "training_completed" if success else "training_failed",
            "results": results,
            "llm_calls": llm_calls,
            "rss_peak_mb": rss_peak_mb,
            "duration_seconds": time.monotonic() - started,
            "held_out_executed": False,
            "next_action": "held_out_evaluation"
            if success
            else "diagnose_training_failure",
        }
        with self.router._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(NULL,?,'domain_training_completed',?,?)",
                (formation["neuron_id"], json.dumps(outcome), utc_now()),
            )
            outcome["event_id"] = _require_insert_id(cursor.lastrowid)
        return outcome

    def certify(
        self, event_id: int, *, correlation_id: str, generate: Any
    ) -> dict[str, Any]:
        """Certify reserved procedural cases with an independently computed oracle.

        The measured capability is bounded rule application in this domain, not
        general intelligence. Control arms never receive learned context.
        """
        from triade.evaluation import EvaluationRun, MetricResult, compare_evaluations
        from triade.learning.evidence_bridge import LearningEvidenceBridge
        from triade.learning.knowledge_probe import build_transfer_probe
        from triade.learning.retrieval import LearningRetriever, build_learning_block
        from triade.regression import MetricPolicy, RegressionGate

        with self.router._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM neuron_education_events WHERE event_type='domain_training_completed' AND json_extract(payload_json,'$.admission_event_id')=? ORDER BY id DESC LIMIT 1",
                (event_id,),
            ).fetchone()
            old = conn.execute(
                "SELECT payload_json FROM neuron_education_events WHERE event_type='domain_certification_completed' AND json_extract(payload_json,'$.admission_event_id')=? ORDER BY id DESC LIMIT 1",
                (event_id,),
            ).fetchone()
        if rows is None:
            raise ValueError("completed_training_required")
        training = json.loads(rows[0])
        if training.get("correlation_id") != correlation_id:
            raise ValueError("training_lineage_mismatch")
        if training.get("status") != "training_completed":
            raise ValueError("successful_training_required")
        certification_attempt = self.certification_attempt(event_id)
        if old is not None and certification_attempt is None:
            return json.loads(old[0])
        curriculum = training["curriculum"]
        canonical = {k: v for k, v in curriculum.items() if k != "sha256"}
        if (
            hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
            != curriculum["sha256"]
        ):
            raise ValueError("curriculum_manifest_changed")
        train_inputs = {x["input_value"] for x in curriculum["cases"]["training"]}
        held_out = curriculum["cases"]["held_out"]
        if not held_out or train_inputs & {x["input_value"] for x in held_out}:
            raise ValueError("held_out_contaminated")
        candidate_id, neuron_id = training["candidate_id"], training["neuron_id"]
        self.router._verified_candidate(candidate_id)
        evaluation_id = "admission-evaluation-" + uuid4().hex
        base = {
            "admission_event_id": event_id,
            "candidate_id": candidate_id,
            "neuron_id": neuron_id,
            "certification_attempt": certification_attempt,
            "correlation_id": correlation_id,
            "curriculum_hash": curriculum["sha256"],
            "evaluation_id": evaluation_id,
            "threshold": curriculum["success_rate_min"],
        }
        with self.router._connect() as conn:
            conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(NULL,?,'domain_certification_started',?,?)",
                (neuron_id, json.dumps(base), utc_now()),
            )
        started = time.monotonic()
        budget = float(curriculum["resource_profile"]["max_runtime_seconds"])
        arms: dict[str, list[dict[str, Any]]] = {
            "baseline": [],
            "treatment": [],
            "negative_control": [],
        }
        rss_peak_mb, calls = 0.0, 0
        import psutil

        for arm, results in arms.items():
            retriever = (
                LearningRetriever(self.router.db_path, allowed_states=frozenset())
                if arm != "treatment"
                else LearningRetriever(self.router.db_path)
            )
            for case in held_out:
                remaining = budget - (time.monotonic() - started)
                rss_peak_mb = max(
                    rss_peak_mb, psutil.Process().memory_info().rss / 1024**2
                )
                probe = build_transfer_probe(
                    self.router.db_path, candidate_id, case["input_value"]
                )
                if probe is None or probe.expected != case["reference"]:
                    raise ValueError("curriculum_source_changed")
                run_id = f"{evaluation_id}:{arm}:{case['case_id']}"
                decision = retriever.retrieve_decision(
                    probe.question, run_id=run_id, only_candidate_ids={candidate_id}
                )
                retriever.persist_decision(decision)
                response, error, passed = "", None, False
                tick = time.monotonic()
                try:
                    if remaining <= 0 or rss_peak_mb > float(
                        curriculum["resource_profile"]["max_memory_mb"]
                    ):
                        raise RuntimeError("certification_resource_budget_exceeded")
                    if (arm == "treatment") != (candidate_id in decision.injected_ids):
                        raise RuntimeError("certification_context_isolation_failed")
                    calls += 1
                    response = generate(
                        probe,
                        build_learning_block(decision.matches) + "\n" + probe.question,
                        remaining,
                    )
                    passed = bool(probe.evaluator(response))
                except (ValueError, RuntimeError, OSError) as exc:
                    error = str(exc)
                results.append(
                    {
                        "case_id": case["case_id"],
                        "run_id": run_id,
                        "passed": passed,
                        "response": response,
                        "error": error,
                        "reference": probe.expected,
                        "injected_ids": decision.injected_ids,
                        "latency_seconds": time.monotonic() - tick,
                    }
                )

        def measurement(arm):
            results = tuple(
                MetricResult(
                    case_id=x["case_id"],
                    score=float(x["passed"]),
                    passed=x["passed"],
                    actual=x["response"],
                    expected=x["reference"],
                    details={"run_id": x["run_id"]},
                )
                for x in arms[arm]
            )
            return EvaluationRun(
                evaluation_id=f"{evaluation_id}:{arm}",
                suite_id="admission-held-out",
                suite_version="1",
                subject_id=str(neuron_id),
                results=results,
                aggregate_score=sum(x.score for x in results) / len(results),
                created_at=utc_now(),
                metadata={
                    "correlation_id": correlation_id,
                    "curriculum_hash": curriculum["sha256"],
                },
            )

        baseline, treatment, negative = (measurement(arm) for arm in arms)
        comparison = compare_evaluations(baseline, treatment)
        evidence_id = "domain-certification:" + evaluation_id
        bridge = LearningEvidenceBridge(self.router.db_path)
        bridge.declare_hypothesis(
            evidence_id,
            hypothesis="Learned rule transfers to reserved domain tasks",
            capability="domain_rule_application",
            subject_id=str(neuron_id),
            require_regression=True,
        )
        bridge.record_comparison(
            evidence_id,
            baseline=baseline,
            candidate=treatment,
            comparison=comparison,
            artifact_ref=f"sqlite:neuron_education_events:{evaluation_id}",
        )
        regression = RegressionGate(self.router.db_path).evaluate(
            report_id="regression-" + evaluation_id,
            candidate_id=evidence_id,
            capability="domain_rule_application",
            baseline=baseline,
            candidate=treatment,
            policies=tuple(
                MetricPolicy(case_id, severity="critical")
                for case_id in (x["case_id"] for x in held_out)
            ),
            metadata={"correlation_id": correlation_id},
        )
        bridge.record_regression_report(evidence_id, regression)
        success = (
            treatment.aggregate_score >= curriculum["success_rate_min"]
            and treatment.aggregate_score
            > max(baseline.aggregate_score, negative.aggregate_score)
            and comparison.decision == "improved"
            and regression.decision == "pass"
            and not any(x["error"] for xs in arms.values() for x in xs)
        )
        if success:
            bridge.require_improvement(evidence_id)
        outcome = {
            **base,
            "status": "certified" if success else "certification_failed",
            "arms": arms,
            "scores": {
                "baseline": baseline.aggregate_score,
                "treatment": treatment.aggregate_score,
                "negative_control": negative.aggregate_score,
            },
            "evidence_id": evidence_id,
            "regression_report_id": regression.report_id,
            "duration_seconds": time.monotonic() - started,
            "rss_peak_mb": rss_peak_mb,
            "llm_calls": calls,
            "competence_certified": success,
            "activated": success,
            "stable_memory_written": False,
        }
        with self.router._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if success:
                current = conn.execute(
                    "SELECT status FROM neurons WHERE id=?", (neuron_id,)
                ).fetchone()
                if current is None or current[0] != "candidate":
                    raise ValueError("activation_requires_candidate_state")
                conn.execute(
                    "UPDATE neurons SET status='active',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (neuron_id,),
                )
                conn.execute(
                    "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(NULL,?,'domain_neuron_activated',?,?)",
                    (neuron_id, json.dumps(base), utc_now()),
                )
            cursor = conn.execute(
                "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(NULL,?,'domain_certification_completed',?,?)",
                (neuron_id, json.dumps(outcome), utc_now()),
            )
            outcome["event_id"] = _require_insert_id(cursor.lastrowid)
        return outcome

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
        if not _reusable(
            admission,
            domain=admission["domain"],
            correlation_id=correlation_id,
            required_capability=admission["required_capability"],
        ):
            raise ValueError("SPEC_INCOMPLETE_OR_INVALID_LINEAGE")
        self.router._verified_candidate(admission["candidate_id"])
        spec = admission["creator_spec"]
        # Extensions require independent certification too. Never mutate the
        # parent's contract on the strength of a semantic proposal alone.
        if admission["decision"] == "EXTEND_EXISTING_NEURON":
            return {
                "status": "blocked",
                "reason": "extension_requires_held_out_evidence",
                "correlation_id": correlation_id,
                "admission_event_id": event_id,
            }
        registry = NeuronRegistry(self.router.db_path)
        candidate_spec = NeuronSpec(
            **{
                key: value
                for key, value in spec.items()
                if key in NeuronSpec.__dataclass_fields__
            }
        )
        candidate_spec.status = "candidate"
        neuron_id = registry.register(
            candidate_spec,
            contract_payload={
                **spec,
                "admission_event_id": event_id,
                "candidate_id": admission["candidate_id"],
                "correlation_id": correlation_id,
                "competence_certified": False,
                "activation_policy": {
                    "default": "candidate_only",
                    "auto_approve": False,
                },
            },
            conflict_policy="create_only",
        )
        receipt = {
            "status": "candidate",
            "neuron_id": neuron_id,
            "correlation_id": correlation_id,
            "admission_event_id": event_id,
            "training_status": "pending_executable_curriculum",
            "competence_certified": False,
            "activated": False,
        }
        with self.router._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id FROM neuron_education_events WHERE event_type='domain_candidate_formed' AND json_extract(payload_json,'$.admission_event_id')=?",
                (event_id,),
            ).fetchone()
            if existing is None:
                cursor = conn.execute(
                    "INSERT INTO neuron_education_events(session_id,neuron_id,event_type,payload_json,created_at) VALUES(NULL,?,'domain_candidate_formed',?,?)",
                    (neuron_id, json.dumps(receipt), utc_now()),
                )
                receipt["event_id"] = _require_insert_id(cursor.lastrowid)
            else:
                receipt["event_id"] = int(existing["id"])
        return receipt

    def request(
        self,
        candidate_id: str,
        *,
        correlation_id: str,
        required_capability: str = "verified_knowledge_application",
    ) -> dict[str, Any]:
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
                    result,
                    domain=domain,
                    correlation_id=correlation_id,
                    required_capability=required_capability,
                ):
                    return {**result, "event_id": int(prior["id"])}
            rows = conn.execute(
                """SELECT id,domain,contract_json FROM neurons
                WHERE status IN ('experimental','active','stable') ORDER BY id"""
            ).fetchall()
            ranked: list[tuple[int, int]] = []
            for row in rows:
                overlap = len(
                    _tokens(domain.replace("_", " "))
                    & _tokens(str(row["domain"]).replace("_", " "))
                )
                if overlap:
                    ranked.append((overlap, int(row["id"])))
            parent = (
                max(ranked, key=lambda item: (item[0], -item[1]))[1] if ranked else None
            )
            decision = (
                "EXTEND_EXISTING_NEURON" if parent is not None else "CREATE_NEW_NEURON"
            )
            request_id = (
                "admission-"
                + hashlib.sha256(
                    f"{candidate_id}:{domain}:{required_capability}:{correlation_id}:{len(previous)}".encode()
                ).hexdigest()[:24]
            )
            evidence = conn.execute(
                """SELECT id,artifact_ref FROM learning_evidence
                WHERE candidate_id=? AND decision='improved'
                ORDER BY updated_at DESC LIMIT 1""",
                (candidate_id,),
            ).fetchone()
            formed = form_candidate(
                {
                    "name": request_id,
                    "mission": f"Evaluar y aplicar conocimiento verificable del dominio {domain} en tareas posteriores distintas, midiendo errores y regresiones.",
                    "domain": domain,
                    "source": "verified_learning_domain_need",
                    "risk_level": str(candidate["risk_level"] or "low"),
                    "inputs_allowed": [
                        "verified_knowledge",
                        "evidence_refs",
                        "task_context",
                        "verification_reports",
                    ],
                    "outputs_allowed": [
                        "knowledge_application",
                        "execution_result",
                        "verification_request",
                    ],
                    "success_metrics": [
                        "success_rate",
                        "error_rate",
                        "latency_ms",
                        "resource_usage",
                        "held_out_generalization",
                    ],
                }
            )
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
                "evidence_refs": [
                    f"sqlite:learning_evidence:{evidence['id']}",
                    str(evidence["artifact_ref"] or ""),
                ],
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
            return {**result, "event_id": _require_insert_id(cursor.lastrowid)}
