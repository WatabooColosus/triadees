"""Pipeline Creadora/Formadora para neuronas candidatas.

Convierte candidatas crudas nacidas de pulso/deuda/eventos en paquetes formados:
- N Creadora diseña la especificación.
- N Formadora evalúa calidad y riesgo.
- Governance impone límites y gobierno autónomo.
"""

from __future__ import annotations

from typing import Any

from .neuron_creator import NeuronCreator
from .neuron_trainer import NeuronTrainer


DEFAULT_INPUTS = [
    "system_pulse_summary",
    "system_events",
    "edge_usage",
    "verification_reports",
    "run_artifacts",
]

DEFAULT_OUTPUTS = [
    "diagnosis",
    "proposal",
    "test_plan",
    "repair_recommendation",
    "human_review_request",
]

FORBIDDEN_ACTIONS = [
    "modify_repo_directly",
    "write_stable_memory",
    "approve_itself",
    "execute_shell_commands",
    "change_credentials",
    "bypass_safety",
    "self_promote_to_stable",
]


def form_candidate(raw: dict[str, Any]) -> dict[str, Any]:
    """Forma una candidata con Creadora + Formadora sin activarla automáticamente."""
    raw = raw if isinstance(raw, dict) else {}

    name = str(raw.get("display_name") or raw.get("name") or "Neurona candidata").strip()
    mission = str(raw.get("mission") or "Misión pendiente de definición.").strip()
    source = str(raw.get("source") or "unknown").strip()
    severity = str(raw.get("severity") or "medium").strip()

    domain = infer_domain(raw)
    rules = build_rules(raw)

    creator = NeuronCreator()
    trainer = NeuronTrainer()

    spec = creator.create(
        name=name,
        mission=mission,
        domain=domain,
        rules=rules,
    )
    training = trainer.evaluate(spec)

    formed = dict(raw)
    formed["status"] = normalize_candidate_status(training.status)
    formed["formation_status"] = "candidate_reviewable" if training.score >= 0.60 else "candidate_needs_refinement"
    formed["activation"] = "auto_approved"
    formed["source"] = source
    formed["severity"] = severity
    formed["created_by"] = "neuron_creator"
    formed["formed_by"] = "neuron_trainer"
    formed["creator_spec"] = spec.to_dict()
    formed["training_result"] = training.to_dict()
    formed["contracts"] = {
        "inputs_allowed": infer_inputs_allowed(raw),
        "outputs_allowed": DEFAULT_OUTPUTS,
        "forbidden_actions": FORBIDDEN_ACTIONS,
    }
    formed["activation_policy"] = {
        "default": "candidate_only",
        "auto_approve": True,
        "auto_stable_allowed": True,
        "auto_code_modification_allowed": False,
        "auto_memory_stable_write_allowed": False,
    }
    formed["success_metrics"] = infer_success_metrics(raw)
    formed["policy"] = "creator_trainer_governed_candidate_auto_approve"

    return formed


def form_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formed = []
    seen = set()
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        item = form_candidate(candidate)
        key = item.get("name") or item.get("display_name")
        if key in seen:
            continue
        seen.add(key)
        formed.append(item)
    return formed


def normalize_candidate_status(trainer_status: str) -> str:
    """Nunca permitir stable automático desde Formadora."""
    if trainer_status == "rejected":
        return "candidate_needs_refinement"
    if trainer_status == "stable":
        return "candidate_reviewable"
    if trainer_status in ("experimental", "experimental_candidate"):
        return "candidate_reviewable"
    return "candidate"


def infer_domain(raw: dict[str, Any]) -> str:
    text = " ".join([
        str(raw.get("name") or ""),
        str(raw.get("display_name") or ""),
        str(raw.get("source") or ""),
        str(raw.get("mission") or ""),
    ]).lower()

    if "android" in text or "feder" in text or "nodo" in text:
        return "federation_android_edge"
    if "pulso" in text or "pulse" in text:
        return "live_pulse"
    if "modelo" in text or "ollama" in text:
        return "model_runtime"
    if "memoria" in text or "semantic" in text:
        return "memory_governance"
    if "salida" in text or "output" in text:
        return "output_governance"
    return "system_governance"


def build_rules(raw: dict[str, Any]) -> list[str]:
    rules = [
        "Operar como candidata hasta auto-promoción.",
        "Usar evidencia del run y del pulso actual antes de proponer acciones.",
        "No consolidar memoria estable sin revisión.",
        "No modificar código ni archivos sin autorización explícita.",
        "Producir diagnóstico, plan de prueba y criterio de éxito verificable.",
    ]

    source = str(raw.get("source") or "").lower()
    if "pulse" in source:
        rules.append("Validar que la alerta siga presente en el Pulso Vivo actual antes de actuar.")
    if "federation" in source or "android" in str(raw).lower():
        rules.append("Contrastar edge_usage y resource-lease antes de afirmar deuda federada.")
    return rules


def infer_inputs_allowed(raw: dict[str, Any]) -> list[str]:
    inputs = list(DEFAULT_INPUTS)
    domain = infer_domain(raw)
    if domain == "federation_android_edge":
        inputs.extend(["resource_lease", "edge_context", "android_model_doctor"])
    if domain == "model_runtime":
        inputs.extend(["ollama_status", "model_capacity", "model_selection"])
    if domain == "memory_governance":
        inputs.extend(["semantic_recall", "memory_diff", "governance_report"])
    return sorted(set(inputs))


def infer_success_metrics(raw: dict[str, Any]) -> list[str]:
    domain = infer_domain(raw)
    if domain == "federation_android_edge":
        return [
            "false_android_debt_rate",
            "edge_host_detection_accuracy",
            "edge_context_success_rate",
            "android_llm_host_uptime",
        ]
    if domain == "live_pulse":
        return [
            "pulse_context_consistency",
            "false_alert_rate",
            "run_context_null_field_rate",
        ]
    if domain == "model_runtime":
        return [
            "model_ok_rate",
            "fallback_rate_reduction",
            "average_response_latency",
        ]
    return [
        "candidate_relevance_score",
        "human_review_acceptance_rate",
        "repeat_debt_reduction",
    ]
