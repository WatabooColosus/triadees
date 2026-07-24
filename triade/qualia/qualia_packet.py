"""QualiaPacket: paquete unificado que encapsula una experiencia completa de Qualia.

Agrupa los 5 tipos de paquete existentes (NeuronExperience, QualiaSignal,
CentralKnowledgePacket, StorageMemoryPacket, QualiaState) en un único
objeto inmutable con metadatos de integridad, continuidad y significado.

Diseño retrocompatible: QualiaPacket se construye A PARTIR de los paquetes
existentes sin reemplazarlos. Es una capa de integración, no sustitución.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import (
    CentralKnowledgePacket,
    NeuronExperience,
    QualiaSignal,
    QualiaState,
    StorageMemoryPacket,
    new_qualia_id,
)
from triade.core.contracts import utc_now


@dataclass(slots=True)
class ContinuityChain:
    """Cadena de continuidad: referencia a experiencias previas del mismo hilo."""

    chain_id: str = field(default_factory=lambda: new_qualia_id("chain"))
    parent_packet_id: str = ""
    parent_run_id: str = ""
    depth: int = 0
    hops: list[str] = field(default_factory=list)
    bridged_sessions: int = 0

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
class MeaningScore:
    """Puntuación de significado calculada para una experiencia."""

    relevance: float = 0.0
    impact: float = 0.0
    novelty: float = 0.0
    identity_alignment: float = 0.0
    composite: float = 0.0
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "relevance": round(self.relevance, 4),
            "impact": round(self.impact, 4),
            "novelty": round(self.novelty, 4),
            "identity_alignment": round(self.identity_alignment, 4),
            "composite": round(self.composite, 4),
            "rationale": self.rationale,
        }


@dataclass(slots=True)
class FragmentationReport:
    """Reporte de fragmentación: mide coherencia entre experiencias del run."""

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
class QualiaPacket:
    """Paquete unificado de una experiencia Qualia completa.

    Contiene:
    - experience: la experiencia de neurona original
    - signal: la señal Qualia extraída
    - central_packet: paquete para la Neurona Central
    - storage_packet: paquete para la Bodega
    - state: snapshot de estado Qualia del run
    - continuity: cadena de continuidad con experiencias previas
    - meaning: puntuación de significado calculada
    - fragmentation: reporte de fragmentación del run
    - metadata: campos auxiliares (emotion, tension, curiosity, etc.)
    """

    id: str = field(default_factory=lambda: new_qualia_id("qpacket"))
    run_id: str = ""
    created_at: str = field(default_factory=utc_now)

    experience: NeuronExperience | None = None
    signal: QualiaSignal | None = None
    central_packet: CentralKnowledgePacket | None = None
    storage_packet: StorageMemoryPacket | None = None
    state: QualiaState | None = None

    continuity: ContinuityChain = field(default_factory=ContinuityChain)
    meaning: MeaningScore = field(default_factory=MeaningScore)
    fragmentation: FragmentationReport = field(default_factory=FragmentationReport)

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "experience": self.experience.to_dict() if self.experience else None,
            "signal": self.signal.to_dict() if self.signal else None,
            "central_packet": self.central_packet.to_dict() if self.central_packet else None,
            "storage_packet": self.storage_packet.to_dict() if self.storage_packet else None,
            "state": self.state.to_dict() if self.state else None,
            "continuity": self.continuity.to_dict(),
            "meaning": self.meaning.to_dict(),
            "fragmentation": self.fragmentation.to_dict(),
            "metadata": dict(self.metadata),
        }

    def summary(self) -> str:
        parts = [f"QualiaPacket {self.id}"]
        if self.experience:
            parts.append(f"obs={self.experience.observation[:60]}")
        if self.signal:
            parts.append(f"signal={self.signal.signal_type}")
        if self.meaning.composite > 0:
            parts.append(f"meaning={self.meaning.composite:.3f}")
        if self.continuity.depth > 0:
            parts.append(f"chain_depth={self.continuity.depth}")
        if self.fragmentation.drift_detected:
            parts.append("DRIFT")
        return " | ".join(parts)


def build_qualia_packet(
    *,
    run_id: str,
    experience: NeuronExperience,
    signal: QualiaSignal,
    state: QualiaState,
    central_packet: CentralKnowledgePacket | None = None,
    storage_packet: StorageMemoryPacket | None = None,
    continuity: ContinuityChain | None = None,
    meaning: MeaningScore | None = None,
    fragmentation: FragmentationReport | None = None,
    metadata: dict[str, Any] | None = None,
) -> QualiaPacket:
    """Construye un QualiaPacket a partir de componentes existentes."""
    return QualiaPacket(
        run_id=run_id,
        experience=experience,
        signal=signal,
        state=state,
        central_packet=central_packet,
        storage_packet=storage_packet,
        continuity=continuity or ContinuityChain(),
        meaning=meaning or MeaningScore(),
        fragmentation=fragmentation or FragmentationReport(),
        metadata=metadata or {},
    )
