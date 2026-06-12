"""Router determinista de experiencias neuronales hacia paquetes Qualia."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .contracts import CentralKnowledgePacket, NeuronExperience, QualiaSignal, StorageMemoryPacket

RISK_NUMERIC = {"low": 0.15, "medium": 0.45, "high": 0.75, "critical": 1.0}


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


@dataclass(slots=True)
class QualiaBundle:
    experience: NeuronExperience
    signal: QualiaSignal
    central_packet: CentralKnowledgePacket
    storage_packet: StorageMemoryPacket
    learning_candidate: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "experience": self.experience.to_dict(),
            "signal": self.signal.to_dict(),
            "central_packet": self.central_packet.to_dict(),
            "storage_packet": self.storage_packet.to_dict(),
            "learning_candidate": self.learning_candidate,
        }


class QualiaRouter:
    """Convierte una experiencia en señales, contexto central, almacenamiento y aprendizaje candidato."""

    def route(self, experience: NeuronExperience) -> QualiaBundle:
        signal = self.to_signal(experience)
        central = self.to_central_packet(experience)
        storage = self.to_storage_packet(experience)
        learning = self.to_learning_candidate(experience)
        return QualiaBundle(experience=experience, signal=signal, central_packet=central, storage_packet=storage, learning_candidate=learning)

    def to_signal(self, experience: NeuronExperience) -> QualiaSignal:
        risk_value = RISK_NUMERIC.get(str(experience.risk).lower(), 0.45)
        emotional = experience.emotional_signal if isinstance(experience.emotional_signal, dict) else {}
        valence = float(emotional.get("valence", 0.0) or 0.0)
        urgency = _clamp(max(risk_value, float(emotional.get("urgency", 0.0) or 0.0)))
        curiosity = _clamp(0.25 + (0.35 if experience.extracted_pattern else 0.0) + (0.25 if experience.proposed_learning else 0.0))
        intensity = _clamp(max(experience.confidence, experience.usefulness, risk_value))
        signal_type = "learning_candidate" if experience.proposed_learning else "neuron_observation"
        tone_hint = "cautious" if risk_value >= 0.7 else "constructive"
        return QualiaSignal(
            run_id=experience.run_id,
            experience_id=experience.id,
            signal_type=signal_type,
            intensity=intensity,
            valence=_clamp((valence + 1.0) / 2.0) if valence < 0 else _clamp(valence),
            urgency=urgency,
            curiosity=curiosity,
            risk=risk_value,
            confidence=_clamp(experience.confidence),
            tone_hint=tone_hint,
            reason=experience.observation[:500] or experience.mission[:500],
        )

    def to_central_packet(self, experience: NeuronExperience) -> CentralKnowledgePacket:
        claim = experience.extracted_pattern or experience.observation or experience.mission
        hypothesis = experience.proposed_learning or experience.extracted_pattern or "Revisar experiencia neuronal antes de usarla como contexto."
        validation = "verified_context_allowed" if experience.confidence >= 0.85 and str(experience.risk) == "low" else "verify_before_use"
        return CentralKnowledgePacket(
            run_id=experience.run_id,
            experience_id=experience.id,
            claim=claim[:1000],
            hypothesis=hypothesis[:1000],
            decision_hint="usar como hipótesis contextual, no como verdad estable",
            validation_need=validation,
            related_goals=[experience.mission] if experience.mission else [],
            confidence=_clamp(experience.confidence),
            evidence_refs=list(experience.evidence_refs),
            status="verified_context" if validation == "verified_context_allowed" else "hypothesis",
        )

    def to_storage_packet(self, experience: NeuronExperience) -> StorageMemoryPacket:
        content = "\n".join(part for part in [
            f"mission: {experience.mission}" if experience.mission else "",
            f"observation: {experience.observation}" if experience.observation else "",
            f"pattern: {experience.extracted_pattern}" if experience.extracted_pattern else "",
            f"proposed_learning: {experience.proposed_learning}" if experience.proposed_learning else "",
        ] if part).strip()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else ""
        return StorageMemoryPacket(
            run_id=experience.run_id,
            experience_id=experience.id,
            memory_type="candidate",
            category="qualia_experience",
            subcategory=experience.source_type or experience.neuron_type,
            content=content,
            source=experience.source or "qualia_bus",
            content_hash=digest,
            confidence=_clamp(experience.confidence),
            verification_status="unverified",
            promotion_status="candidate",
        )

    def to_learning_candidate(self, experience: NeuronExperience) -> dict[str, Any] | None:
        if not experience.proposed_learning:
            return None
        return {
            "content": experience.proposed_learning,
            "source_type": "qualia_bus",
            "source_ref": f"qualia:{experience.id}",
            "title": f"Aprendizaje Qualia · {experience.neuron_type or experience.source_type}",
            "domain": experience.neuron_type or experience.source_type or "qualia",
            "risk_level": str(experience.risk or "low"),
            "evidence_refs": list(experience.evidence_refs),
        }
