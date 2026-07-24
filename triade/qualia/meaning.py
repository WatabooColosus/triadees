"""MeaningEngine: calcula el significado y propósito de cada experiencia Qualia.

No asigna propósito filosófico: evalúa impacto funcional, relevancia
para la misión, novedad y alineación con la identidad del sistema.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any

from .contracts import NeuronExperience, QualiaState


@dataclass(slots=True)
class MeaningProfile:
    """Perfil de significado pre-calculado para un dominio o tipo de experiencia."""

    domain: str = ""
    base_relevance: float = 0.5
    base_impact: float = 0.5
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "base_relevance": round(self.base_relevance, 4),
            "base_impact": round(self.base_impact, 4),
            "keywords": list(self.keywords),
        }


# Perfiles de dominio predefinidos
DOMAIN_PROFILES: dict[str, MeaningProfile] = {
    "mission": MeaningProfile(
        domain="mission",
        base_relevance=0.9,
        base_impact=0.85,
        keywords=["misión", "objetivo", "meta", "propósito", "cumplir"],
    ),
    "learning": MeaningProfile(
        domain="learning",
        base_relevance=0.75,
        base_impact=0.7,
        keywords=["aprender", "conocimiento", "patrón", "descubrir", "hipótesis"],
    ),
    "safety": MeaningProfile(
        domain="safety",
        base_relevance=0.85,
        base_impact=0.9,
        keywords=["seguridad", "riesgo", "protección", "límite", "amenaza"],
    ),
    "self_awareness": MeaningProfile(
        domain="self_awareness",
        base_relevance=0.7,
        base_impact=0.65,
        keywords=["introspección", "estado", "emoción", "carga", "fatiga"],
    ),
    "social": MeaningProfile(
        domain="social",
        base_relevance=0.6,
        base_impact=0.55,
        keywords=["usuario", "comunicación", "respuesta", "interaction"],
    ),
    "error": MeaningProfile(
        domain="error",
        base_relevance=0.7,
        base_impact=0.8,
        keywords=["error", "fallo", "excepción", "problema", "falló"],
    ),
    "general": MeaningProfile(
        domain="general",
        base_relevance=0.5,
        base_impact=0.5,
        keywords=[],
    ),
}

MISSION_KEYWORDS = {"misión", "objetivo", "meta", "propósito", "cumplir", "entregar"}
IDENTITY_KEYWORDS = {"identidad", "valores", "principios", "ética", "virtud", "tensión"}
NOVELTY_KEYWORDS = {"nuevo", "descubrir", "primera vez", "sin precedent", "novel"}


class MeaningEngine:
    """Calcula el significado de experiencias Qualia basándose en:

    1. Relevancia: qué tan relacionada está con la misión activa.
    2. Impacto: qué tan significativa es para el sistema.
    3. Novedad: qué tan nueva es la información.
    4. Alineación con identidad: qué tan consistente con los valores.
    5. Composición: ponderación de los anteriores.
    """

    def __init__(self) -> None:
        self._seen_hashes: dict[str, float] = {}

    def score(
        self,
        *,
        experience: NeuronExperience,
        state: QualiaState | None = None,
        mission_context: str = "",
        identity_values: list[str] | None = None,
    ) -> dict[str, Any]:
        """Calcula el significado de una experiencia.

        Returns un dict con los campos de MeaningScore.
        """
        obs = getattr(experience, "observation", "") or ""
        pattern = getattr(experience, "extracted_pattern", "") or ""
        mission = getattr(experience, "mission", "") or ""
        source = getattr(experience, "source", "") or ""
        combined_text = f"{obs} {pattern} {mission}".lower()

        profile = self._domain_profile(combined_text)

        relevance = self._calc_relevance(
            combined_text, mission, mission_context, profile
        )
        impact = self._calc_impact(combined_text, experience, state, profile)
        novelty = self._calc_novelty(obs, pattern)
        identity_alignment = self._calc_identity(
            combined_text, identity_values or []
        )

        weights = (0.30, 0.25, 0.25, 0.20)
        composite = (
            relevance * weights[0]
            + impact * weights[1]
            + novelty * weights[2]
            + identity_alignment * weights[3]
        )
        composite = max(0.0, min(1.0, composite))

        rationale = self._rationale(
            profile.domain, relevance, impact, novelty, identity_alignment
        )

        return {
            "relevance": round(relevance, 4),
            "impact": round(impact, 4),
            "novelty": round(novelty, 4),
            "identity_alignment": round(identity_alignment, 4),
            "composite": round(composite, 4),
            "rationale": rationale,
        }

    def score_batch(
        self,
        *,
        experiences: list[NeuronExperience],
        state: QualiaState | None = None,
        mission_context: str = "",
    ) -> list[dict[str, Any]]:
        """Puntúa un lote de experiencias."""
        return [
            self.score(
                experience=exp,
                state=state,
                mission_context=mission_context,
            )
            for exp in experiences
        ]

    def _domain_profile(self, text: str) -> MeaningProfile:
        best_profile = DOMAIN_PROFILES["general"]
        best_score = 0.0
        for name, profile in DOMAIN_PROFILES.items():
            if name == "general":
                continue
            hits = sum(1 for kw in profile.keywords if kw in text)
            if hits > best_score:
                best_score = hits
                best_profile = profile
        return best_profile

    def _calc_relevance(
        self,
        text: str,
        mission: str,
        mission_context: str,
        profile: MeaningProfile,
    ) -> float:
        base = profile.base_relevance
        mission_bonus = 0.0
        if mission or mission_context:
            mission_text = f"{mission} {mission_context}".lower()
            shared = sum(1 for w in mission_text.split() if w in text)
            mission_bonus = min(0.3, shared * 0.05)
        return min(1.0, base + mission_bonus)

    def _calc_impact(
        self,
        text: str,
        experience: NeuronExperience,
        state: QualiaState | None,
        profile: MeaningProfile,
    ) -> float:
        base = profile.base_impact
        emotion_bonus = 0.0
        if state:
            emotion_val = getattr(state, "emotional_valence", 0.0)
            emotion_bonus = abs(float(emotion_val or 0.0)) * 0.15
        urgency_bonus = 0.0
        if state and getattr(state, "urgency", 0.0) > 0.6:
            urgency_bonus = 0.1
        error_bonus = 0.1 if "error" in text or "falló" in text else 0.0
        return min(1.0, base + emotion_bonus + urgency_bonus + error_bonus)

    def _calc_novelty(self, obs: str, pattern: str) -> float:
        if not obs and not pattern:
            return 0.3
        h = hashlib.md5(f"{obs}|{pattern}".encode()).hexdigest()[:12]
        if h in self._seen_hashes:
            repeat_count = sum(
                1 for k in self._seen_hashes if k.startswith(h[:8])
            )
            return max(0.1, 0.8 - repeat_count * 0.1)
        self._seen_hashes[h] = 1.0
        return 0.7

    def _calc_identity(
        self, text: str, identity_values: list[str]
    ) -> float:
        id_hits = sum(1 for kw in IDENTITY_KEYWORDS if kw in text)
        value_hits = sum(1 for v in identity_values if v.lower() in text)
        return min(1.0, 0.4 + id_hits * 0.1 + value_hits * 0.05)

    def _rationale(
        self,
        domain: str,
        relevance: float,
        impact: float,
        novelty: float,
        identity_alignment: float,
    ) -> str:
        parts = [f"domain={domain}"]
        if relevance > 0.7:
            parts.append("high_relevance")
        if impact > 0.7:
            parts.append("high_impact")
        if novelty > 0.6:
            parts.append("novel")
        if identity_alignment > 0.6:
            parts.append("identity_aligned")
        return ", ".join(parts)
