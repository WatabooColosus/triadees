"""Pipeline primario de propuesta de neuronas.

Usado cuando la Central detecta que el sistema debe proponer una neurona nueva.
La propuesta nace completa, pero siempre como candidate y con promoción humana.
"""

from __future__ import annotations

from typing import Any

from .neuron_creator import NeuronCreator, NeuronSpec
from .neuron_trainer import NeuronTrainer, NeuronTrainingResult


FORBIDDEN_ACTIONS = [
    "modify_repo_directly",
    "write_stable_memory",
    "self_approve",
    "bypass_safety",
    "execute_external_action_without_approval",
    "self_promote_to_stable",
]


def unique_list(values: list[str]) -> list[str]:
    """Deduplica preservando orden."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values or []:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def build_primary_neuron_package(
    *,
    name: str,
    mission: str,
    domain: str,
    source_run: str,
    user_text: str,
    intent: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construye una propuesta primaria completa sin activarla."""
    context = context or {}
    domain = infer_primary_domain(name=name, mission=mission, domain=domain, intent=intent, context=context)

    spec = NeuronCreator().create(
        name=name,
        mission=mission,
        domain=domain,
        rules=build_rules(domain),
        triggers=build_triggers(domain, intent, user_text),
        inputs_allowed=build_inputs_allowed(domain),
        outputs_allowed=build_outputs_allowed(domain),
        forbidden_actions=FORBIDDEN_ACTIONS,
        success_metrics=build_success_metrics(domain),
        evidence_required=build_evidence_required(domain),
    )
    spec.status = "candidate"
    spec.created_by = "primary_neuron_pipeline"

    # NeuronCreator agrega reglas/prohibiciones base. Deduplicamos para que
    # contracts y creator_spec no repitan acciones críticas.
    spec.rules = unique_list(spec.rules)
    spec.triggers = unique_list(spec.triggers)
    spec.inputs_allowed = unique_list(spec.inputs_allowed)
    spec.outputs_allowed = unique_list(spec.outputs_allowed)
    spec.forbidden_actions = unique_list(spec.forbidden_actions)
    spec.success_metrics = unique_list(spec.success_metrics)
    spec.evidence_required = unique_list(spec.evidence_required)

    assessment = NeuronTrainer().evaluate(spec)

    return {
        "name": spec.name,
        "domain": spec.domain,
        "registered_as": "candidate",
        "activation": "auto_approved",
        "source_run": source_run,
        "creator_spec": spec.to_dict(),
        "training_result": assessment.to_dict(),
        "contracts": {
            "inputs_allowed": spec.inputs_allowed,
            "outputs_allowed": spec.outputs_allowed,
            "forbidden_actions": spec.forbidden_actions,
        },
        "activation_policy": {
            "default": "candidate_only",
            "auto_approve": True,
            "auto_stable_allowed": True,
            "auto_experimental_allowed": True,
            "auto_code_modification_allowed": False,
            "auto_memory_stable_write_allowed": False,
        },
        "success_metrics": spec.success_metrics,
        "evidence_required": spec.evidence_required,
        "proposal_quality": {
            "score": assessment.score,
            "status": assessment.status,
            "contract_complete": is_contract_complete(spec),
            "required_human_review": False,
        },
        "assessment": {
            "score": assessment.score,
            "assessed_status": assessment.status,
            "strengths": assessment.strengths,
            "warnings": assessment.warnings,
            "recommendations": assessment.recommendations,
        },
        "policy": "system_proposes_human_governs_no_auto_stable",
    }


def infer_primary_domain(name: str, mission: str, domain: str, intent: str, context: dict[str, Any]) -> str:
    text = " ".join([
        name or "",
        mission or "",
        domain or "",
        intent or "",
        str(context.get("domain") or ""),
        str(context.get("project_id") or ""),
        str(context.get("active_neuron") or ""),
    ]).lower()

    if any(x in text for x in ["android", "apk", "nodo", "feder"]):
        return "federation_android_edge"
    if any(x in text for x in ["pulso", "estado", "verifica", "audit", "audita", "health"]):
        return "system_governance"
    if any(x in text for x in ["modelo", "ollama", "llm"]):
        return "model_runtime"
    if any(x in text for x in ["memoria", "semantic", "bodega"]):
        return "memory_governance"
    if any(x in text for x in ["salida", "respuesta", "output"]):
        return "output_governance"
    return domain or intent or "general"


def build_rules(domain: str) -> list[str]:
    rules = [
        "Operar dentro del ciclo auditable de Tríade.",
        "No modificar memoria estable sin validación humana.",
        "No ejecutar acciones externas sin autorización explícita.",
        "No aprobarse a sí misma ni elevar su propio estado.",
        "Producir diagnóstico, plan de prueba y criterio de éxito verificable.",
        "Registrar evidencia antes de solicitar promoción.",
    ]

    if domain == "system_governance":
        rules.append("Comparar pulso, artifacts del run y auditorías antes de emitir diagnóstico.")
    elif domain == "federation_android_edge":
        rules.append("Contrastar edge_usage, pulse_context y resource lease antes de afirmar deuda federada.")
    elif domain == "model_runtime":
        rules.append("Separar fallos de modelo, latencia, fallback y ausencia de backend.")
    elif domain == "memory_governance":
        rules.append("Distinguir memoria estable, experimental, episódica y semántica antes de consolidar.")

    return rules


def build_triggers(domain: str, intent: str, user_text: str) -> list[str]:
    base = [
        f"intent:{intent or 'unknown'}",
        "human_or_system_requests_neuron_proposal",
    ]

    if domain == "system_governance":
        base.extend(["pulse_audit_requested", "run_health_check_requested", "candidate_state_review"])
    elif domain == "federation_android_edge":
        base.extend(["android_node_state_changed", "edge_context_failure", "llm_host_detection_changed"])
    elif domain == "model_runtime":
        base.extend(["model_fallback_high", "ollama_unavailable", "latency_threshold_exceeded"])
    elif domain == "memory_governance":
        base.extend(["semantic_recall_inconsistent", "memory_diff_requires_review", "stable_memory_write_requested"])
    else:
        base.append("domain_specific_need_detected")

    if "verifica" in user_text.lower() or "audita" in user_text.lower():
        base.append("explicit_verification_request")

    return sorted(set(base))


def build_inputs_allowed(domain: str) -> list[str]:
    inputs = [
        "input_packet",
        "signals",
        "system_pulse_summary",
        "system_events",
        "run_artifacts",
        "verification_reports",
        "memory_diff",
    ]

    if domain == "system_governance":
        inputs.extend(["audit_reports", "integrity_json", "background_neuron_candidates"])
    elif domain == "federation_android_edge":
        inputs.extend(["edge_context", "edge_usage", "resource_lease", "android_model_doctor"])
    elif domain == "model_runtime":
        inputs.extend(["ollama_status", "model_selection", "model_capacity", "model_events"])
    elif domain == "memory_governance":
        inputs.extend(["semantic_recall", "semantic_continuity", "governance_report"])

    return sorted(set(inputs))


def build_outputs_allowed(domain: str) -> list[str]:
    return [
        "diagnosis",
        "proposal",
        "test_plan",
        "audit_summary",
        "repair_recommendation",
        "human_review_request",
    ]


def build_success_metrics(domain: str) -> list[str]:
    if domain == "system_governance":
        return [
            "audit_consistency_score",
            "false_positive_candidate_rate",
            "run_health_detection_accuracy",
            "human_review_acceptance_rate",
        ]
    if domain == "federation_android_edge":
        return [
            "edge_host_detection_accuracy",
            "false_android_debt_rate",
            "edge_context_success_rate",
            "android_llm_host_uptime",
        ]
    if domain == "model_runtime":
        return [
            "model_ok_rate",
            "fallback_rate_reduction",
            "average_response_latency",
        ]
    if domain == "memory_governance":
        return [
            "memory_retrieval_accuracy",
            "stable_memory_precision",
            "experimental_to_stable_acceptance_rate",
        ]
    return [
        "candidate_relevance_score",
        "human_review_acceptance_rate",
        "repeat_debt_reduction",
    ]


def build_evidence_required(domain: str) -> list[str]:
    evidence = [
        "source_run",
        "input_text",
        "signal_packet",
        "verification_report",
        "human_review",
    ]

    if domain == "system_governance":
        evidence.extend(["system_pulse_summary", "integrity_json", "audit_output"])
    elif domain == "federation_android_edge":
        evidence.extend(["edge_context_json", "pulse_llm_android_host_check", "android_model_doctor_result"])
    elif domain == "model_runtime":
        evidence.extend(["model_event", "ollama_health", "latency_measurement"])
    elif domain == "memory_governance":
        evidence.extend(["memory_diff", "semantic_recall_report", "governance_decision"])

    return sorted(set(evidence))


def is_contract_complete(spec: NeuronSpec) -> bool:
    return bool(
        spec.triggers
        and spec.inputs_allowed
        and spec.outputs_allowed
        and spec.forbidden_actions
        and spec.success_metrics
        and spec.evidence_required
    )
