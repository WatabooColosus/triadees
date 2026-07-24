"""QualiaPacket — Paquete completo de experiencia cualitativa.

Campos requeridos:
- run_id, experience, meaning, continuity, identity, purpose, emotion,
  memory, fragmentation, confidence, evidence, regulation_result

Separado de Hypotálamo — solo encapsula la experiencia.
ContinuEngine (continuity.py) separado de Cristal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now


def _new_qualia_id(prefix: str = "qpacket") -> str:
    import hashlib
    import time
    return f"{prefix}-{int(time.time() * 1000)}-{hashlib.md5(str(time.time()).encode()).hexdigest()[:6]}"


@dataclass(slots=True)
class EmotionVector:
    valence: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0
    label: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valence": round(self.valence, 4),
            "arousal": round(self.arousal, 4),
            "dominance": round(self.dominance, 4),
            "label": self.label,
            "source": self.source,
        }


@dataclass(slots=True)
class MeaningScore:
    relevance: float = 0.0
    impact: float = 0.0
    novelty: float = 0.0
    composite: float = 0.0
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevance": round(self.relevance, 4),
            "impact": round(self.impact, 4),
            "novelty": round(self.novelty, 4),
            "composite": round(self.composite, 4),
            "rationale": self.rationale,
        }


@dataclass(slots=True)
class ContinuityChain:
    chain_id: str = ""
    parent_packet_id: str = ""
    parent_run_id: str = ""
    depth: int = 0
    hops: list[str] = field(default_factory=list)
    bridged_sessions: int = 0

    def __post_init__(self):
        if not self.chain_id:
            self.chain_id = _new_qualia_id("chain")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "parent_packet_id": self.parent_packet_id,
            "parent_run_id": self.parent_run_id,
            "depth": self.depth,
            "hops": list(self.hops),
            "bridged_sessions": self.bridged_sessions,
        }


@dataclass(slots=True)
class IdentitySnapshot:
    core_traits: dict[str, float] = field(default_factory=dict)
    role: str = ""
    values: list[str] = field(default_factory=list)
    alignment_score: float = 0.0
    deviation_from_baseline: float = 0.0
    baseline_version: str = ""
    protected_fields: list[str] = field(default_factory=lambda: ["role", "values"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "core_traits": dict(self.core_traits),
            "role": self.role,
            "values": list(self.values),
            "alignment_score": round(self.alignment_score, 4),
            "deviation_from_baseline": round(self.deviation_from_baseline, 4),
            "baseline_version": self.baseline_version,
            "protected_fields": list(self.protected_fields),
        }


@dataclass(slots=True)
class PurposeVector:
    goal: str = ""
    urgency: float = 0.0
    importance: float = 0.0
    source: str = ""
    constitutional_alignment: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "urgency": round(self.urgency, 4),
            "importance": round(self.importance, 4),
            "source": self.source,
            "constitutional_alignment": round(self.constitutional_alignment, 4),
        }


@dataclass(slots=True)
class MemoryRetrieval:
    episodic_hits: int = 0
    semantic_hits: int = 0
    procedural_hits: int = 0
    relevant_memories: list[dict[str, Any]] = field(default_factory=list)
    context_relevance: float = 0.0
    memory_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "episodic_hits": self.episodic_hits,
            "semantic_hits": self.semantic_hits,
            "procedural_hits": self.procedural_hits,
            "relevant_memories": list(self.relevant_memories),
            "context_relevance": round(self.context_relevance, 4),
            "memory_confidence": round(self.memory_confidence, 4),
        }


@dataclass(slots=True)
class FragmentationReport:
    coherence_score: float = 1.0
    drift_detected: bool = False
    contradictions: list[str] = field(default_factory=list)
    topic_jump_count: int = 0
    recommended_action: str = "continue"

    def to_dict(self) -> dict[str, Any]:
        return {
            "coherence_score": round(self.coherence_score, 4),
            "drift_detected": self.drift_detected,
            "contradictions": list(self.contradictions),
            "topic_jump_count": self.topic_jump_count,
            "recommended_action": self.recommended_action,
        }


@dataclass(slots=True)
class EvidenceVector:
    sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    support_level: str = "none"
    contradictions_found: list[str] = field(default_factory=list)
    reasoning_chain: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": list(self.sources),
            "confidence": round(self.confidence, 4),
            "support_level": self.support_level,
            "contradictions_found": list(self.contradictions_found),
            "reasoning_chain": list(self.reasoning_chain),
        }


@dataclass(slots=True)
class RegulationResult:
    regulated: bool = False
    adjustments: list[str] = field(default_factory=list)
    priority_shift: float = 0.0
    concurrency_limit: int = 0
    suspension_triggered: bool = False
    circuit_breaker_triggered: bool = False
    investigate_triggered: bool = False
    regulation_log: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "regulated": self.regulated,
            "adjustments": list(self.adjustments),
            "priority_shift": round(self.priority_shift, 4),
            "concurrency_limit": self.concurrency_limit,
            "suspension_triggered": self.suspension_triggered,
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "investigate_triggered": self.investigate_triggered,
            "regulation_log": list(self.regulation_log),
        }


@dataclass(slots=True)
class QualiaPacket:
    """Paquete completo de experiencia cualitativa."""

    id: str = ""
    run_id: str = ""
    created_at: str = ""

    experience: dict[str, Any] = field(default_factory=dict)
    meaning: MeaningScore = field(default_factory=MeaningScore)
    continuity: ContinuityChain = field(default_factory=ContinuityChain)
    identity: IdentitySnapshot = field(default_factory=IdentitySnapshot)
    purpose: PurposeVector = field(default_factory=PurposeVector)
    emotion: EmotionVector = field(default_factory=EmotionVector)
    memory: MemoryRetrieval = field(default_factory=MemoryRetrieval)
    fragmentation: FragmentationReport = field(default_factory=FragmentationReport)
    confidence: float = 0.0
    evidence: EvidenceVector = field(default_factory=EvidenceVector)
    regulation_result: RegulationResult = field(default_factory=RegulationResult)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = _new_qualia_id("qpacket")
        if not self.created_at:
            self.created_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "experience": dict(self.experience),
            "meaning": self.meaning.to_dict(),
            "continuity": self.continuity.to_dict(),
            "identity": self.identity.to_dict(),
            "purpose": self.purpose.to_dict(),
            "emotion": self.emotion.to_dict(),
            "memory": self.memory.to_dict(),
            "fragmentation": self.fragmentation.to_dict(),
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence.to_dict(),
            "regulation_result": self.regulation_result.to_dict(),
            "metadata": dict(self.metadata),
        }

    def summary(self) -> str:
        parts = [f"QP {self.id[:20]}"]
        if self.meaning.composite > 0:
            parts.append(f"meaning={self.meaning.composite:.3f}")
        if self.emotion.label:
            parts.append(f"emotion={self.emotion.label}")
        if self.identity.alignment_score > 0:
            parts.append(f"identity={self.identity.alignment_score:.3f}")
        if self.confidence > 0:
            parts.append(f"conf={self.confidence:.3f}")
        if self.fragmentation.drift_detected:
            parts.append("DRIFT")
        if self.regulation_result.regulated:
            parts.append("REGULATED")
        return " | ".join(parts)


def build_qualia_packet(
    *,
    run_id: str,
    experience: dict[str, Any] | None = None,
    meaning: MeaningScore | None = None,
    continuity: ContinuityChain | None = None,
    identity: IdentitySnapshot | None = None,
    purpose: PurposeVector | None = None,
    emotion: EmotionVector | None = None,
    memory: MemoryRetrieval | None = None,
    fragmentation: FragmentationReport | None = None,
    confidence: float = 0.0,
    evidence: EvidenceVector | None = None,
    regulation_result: RegulationResult | None = None,
    metadata: dict[str, Any] | None = None,
) -> QualiaPacket:
    return QualiaPacket(
        run_id=run_id,
        experience=experience or {},
        meaning=meaning or MeaningScore(),
        continuity=continuity or ContinuityChain(),
        identity=identity or IdentitySnapshot(),
        purpose=purpose or PurposeVector(),
        emotion=emotion or EmotionVector(),
        memory=memory or MemoryRetrieval(),
        fragmentation=fragmentation or FragmentationReport(),
        confidence=confidence,
        evidence=evidence or EvidenceVector(),
        regulation_result=regulation_result or RegulationResult(),
        metadata=metadata or {},
    )
