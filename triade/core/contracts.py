"""Contratos de datos iniciales para Tríade Ω.

El MVP usa dataclasses para evitar dependencias externas en la primera fase.
Más adelante estos contratos pueden migrar a Pydantic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

Status = Literal["ok", "warning", "blocked", "failed"]
RiskLevel = Literal["low", "medium", "high", "critical"]
Urgency = Literal["low", "medium", "high"]
SafetyStatus = Literal[
    "approved",
    "approved_with_warning",
    "sandbox_only",
    "requires_human_approval",
    "blocked",
]

NeuronStatus = Literal[
    "candidate",
    "experimental",
    "active_assistant",
    "trusted_worker",
    "stable",
    "rejected",
    "needs_changes",
]

AllowedEffect = Literal[
    "observe",
    "diagnose",
    "propose_learning",
    "influence_plan",
    "influence_response",
    "write_experimental_memory",
    "request_stable_promotion",
]

NEURON_STATUS_EFFECTS: dict[str, tuple[AllowedEffect, ...]] = {
    "candidate": ("observe", "diagnose"),
    "experimental": ("observe", "diagnose", "propose_learning"),
    "active_assistant": ("observe", "diagnose", "propose_learning", "influence_plan"),
    "trusted_worker": (
        "observe", "diagnose", "propose_learning",
        "influence_plan", "influence_response",
        "write_experimental_memory",
    ),
    "stable": (
        "observe", "diagnose", "propose_learning",
        "influence_plan", "influence_response",
        "write_experimental_memory", "request_stable_promotion",
    ),
}

IDENTITY_CORE_FORBIDDEN_EFFECTS: frozenset[str] = frozenset({
    "write_experimental_memory",
    "request_stable_promotion",
})


def utc_now() -> str:
    """Retorna timestamp ISO-8601 en UTC."""
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    """Genera un identificador de run legible y único."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"run-{stamp}-{uuid4().hex[:8]}"


@dataclass(slots=True)
class InputPacket:
    user_input: str
    source: str = "console"
    context: dict[str, Any] = field(default_factory=dict)
    run_id: str = field(default_factory=new_run_id)
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SignalPacket:
    run_id: str
    intent: str
    tone: str
    urgency: Urgency
    risk: RiskLevel
    pv7: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MemoryPacket:
    run_id: str
    episodic_matches: list[dict[str, Any]] = field(default_factory=list)
    semantic_matches: list[dict[str, Any]] = field(default_factory=list)
    identity_matches: list[dict[str, Any]] = field(default_factory=list)
    semantic_recall: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CrystalPacket:
    run_id: str
    ethics: float = 0.8
    depth: float = 0.6
    creativity: float = 0.5
    relation: float = 0.7
    pv7_score: float = 0.5
    stability: float = 0.5
    intensity: float = 0.5
    q_crystal: float = 0.0
    ethics_vector: dict[str, float] = field(default_factory=dict)
    regulation_notes: list[str] = field(default_factory=list)
    decision_notes: list[str] = field(default_factory=list)
    previous_q_crystal: float | None = None
    previous_stability: float | None = None
    q_delta: float = 0.0
    stability_delta: float = 0.0
    temporal_status: str = "baseline"
    temporal_alerts: list[str] = field(default_factory=list)
    history_window: int = 0
    context_scope: str = "source_intent"
    context_key: str = ""
    comparison_basis: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PlanPacket:
    run_id: str
    goal: str
    steps: list[str] = field(default_factory=list)
    structured_steps: list[Any] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    safety_required: bool = True
    budget: Any = None
    rollback: Any = None
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.structured_steps:
            d["structured_steps"] = [
                s.to_dict() if hasattr(s, "to_dict") else s
                for s in self.structured_steps
            ]
        if self.budget and hasattr(self.budget, "to_dict"):
            d["budget"] = self.budget.to_dict()
        if self.rollback and hasattr(self.rollback, "to_dict"):
            d["rollback"] = self.rollback.to_dict()
        return d


@dataclass(slots=True)
class SafetyPacket:
    run_id: str
    status: SafetyStatus
    risk_level: RiskLevel
    risk_types: list[str] = field(default_factory=list)
    reason: str = ""
    required_controls: list[str] = field(default_factory=list)
    human_approval_required: bool = False
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OutputPacket:
    run_id: str
    response: str
    actions_taken: list[str] = field(default_factory=list)
    memory_diff: dict[str, Any] = field(default_factory=dict)
    status: Status = "ok"
    model_provider: str = "template"
    model_name: str = "template-fallback"
    model_ok: bool = False
    model_error: str | None = None
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VerificationReport:
    run_id: str
    status: Status
    coherence_score: float = 0.0
    memory_score: float = 0.0
    safety_score: float = 0.0
    usefulness_score: float = 0.0
    traceability_score: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class NeuronContributionPacket:
    """Paquete formal de contribución de una neurona al ciclo cognitivo.

    Cada activación neuronal produce un NeuronContributionPacket que puede
    influir en plan, respuesta, aprendizaje o memoria experimental según
    los permitted effects del estado de la neurona.
    """

    contribution_id: str = field(default_factory=lambda: f"contrib-{uuid4().hex[:16]}")
    run_id: str = ""
    neuron_id: str = ""
    neuron_name: str = ""
    neuron_status: str = ""
    neuron_domain: str = ""
    activation_reason: str = ""
    diagnosis: str = ""
    proposed_context: dict[str, Any] = field(default_factory=dict)
    proposed_learning: str = ""
    response_influence: str = ""
    confidence: float = 0.0
    risk: RiskLevel = "low"
    evidence_refs: list[str] = field(default_factory=list)
    allowed_effects: list[AllowedEffect] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def has_effect(self, effect: AllowedEffect) -> bool:
        return effect in self.allowed_effects

    def is_identity_core_safe(self) -> bool:
        """Verifica que la contribución no intente modificar identity_core."""
        dangerous = (
            "identity_core" in self.proposed_learning.lower()
            or "identity_core" in self.response_influence.lower()
            or "identity_core" in self.diagnosis.lower()
        )
        return not dangerous
