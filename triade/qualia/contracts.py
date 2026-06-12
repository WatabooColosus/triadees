"""Contratos dataclass para QualiaBus."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from triade.core.contracts import utc_now


def new_qualia_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16]}"


@dataclass(slots=True)
class NeuronExperience:
    id: str = field(default_factory=lambda: new_qualia_id("qexp"))
    run_id: str = ""
    neuron_id: str | int | None = None
    neuron_type: str = "unknown"
    mission: str = ""
    source: str = ""
    source_type: str = "neuron"
    observation: str = ""
    extracted_pattern: str = ""
    proposed_learning: str = ""
    confidence: float = 0.0
    risk: str = "low"
    usefulness: float = 0.0
    emotional_signal: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class QualiaSignal:
    id: str = field(default_factory=lambda: new_qualia_id("qsig"))
    run_id: str = ""
    experience_id: str = ""
    signal_type: str = "observation"
    intensity: float = 0.0
    valence: float = 0.0
    urgency: float = 0.0
    curiosity: float = 0.0
    risk: float = 0.0
    confidence: float = 0.0
    tone_hint: str = "constructive"
    reason: str = ""
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CentralKnowledgePacket:
    id: str = field(default_factory=lambda: new_qualia_id("qcen"))
    run_id: str = ""
    experience_id: str = ""
    claim: str = ""
    hypothesis: str = ""
    decision_hint: str = ""
    validation_need: str = "verify_before_use"
    related_goals: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence_refs: list[str] = field(default_factory=list)
    status: str = "hypothesis"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StorageMemoryPacket:
    id: str = field(default_factory=lambda: new_qualia_id("qmem"))
    run_id: str = ""
    experience_id: str = ""
    memory_type: str = "candidate"
    category: str = "qualia_experience"
    subcategory: str = "neuron_observation"
    content: str = ""
    source: str = "qualia_bus"
    content_hash: str = ""
    confidence: float = 0.0
    verification_status: str = "unverified"
    promotion_status: str = "candidate"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class QualiaState:
    run_id: str
    curiosity: float = 0.0
    confidence: float = 0.0
    risk: float = 0.0
    urgency: float = 0.0
    coherence: float = 0.0
    novelty: float = 0.0
    usefulness: float = 0.0
    saturation: float = 0.0
    dominant_signal: str = "none"
    recommended_action: str = "observe"
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
