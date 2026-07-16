"""Introspección operativa sobre experiencias y estados de QualiaBus.

No afirma experiencia subjetiva. Convierte señales internas en preguntas,
hipótesis y acciones de investigación gobernadas y auditables.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from triade.core.contracts import utc_now

from .contracts import NeuronExperience, QualiaState, new_qualia_id


@dataclass(slots=True)
class IntrospectionReport:
    id: str = field(default_factory=lambda: new_qualia_id("qintro"))
    run_id: str = ""
    trigger: str = "routine_reflection"
    observed_state: dict[str, Any] = field(default_factory=dict)
    observations: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    knowledge_gaps: list[str] = field(default_factory=list)
    self_questions: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    curiosity: float = 0.0
    requires_verification: bool = True
    status: str = "hypothesis"
    evidence_refs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QualiaIntrospector:
    """Observa el flujo Qualia y formula preguntas sobre sus propios vacíos."""

    def reflect(
        self,
        *,
        run_id: str,
        state: QualiaState,
        experiences: Iterable[NeuronExperience | dict[str, Any]],
    ) -> IntrospectionReport:
        rows = [self._as_dict(item) for item in experiences]
        observations = [str(row.get("observation", "")).strip() for row in rows]
        observations = [item for item in observations if item]
        patterns = [str(row.get("extracted_pattern", "")).strip() for row in rows]
        patterns = [item for item in patterns if item]
        learnings = [str(row.get("proposed_learning", "")).strip() for row in rows]
        learnings = [item for item in learnings if item]
        evidence_refs = sorted({ref for row in rows for ref in row.get("evidence_refs", []) if ref})

        contradictions = self._detect_contradictions(rows)
        gaps: list[str] = []
        questions: list[str] = []
        hypotheses: list[str] = []
        actions: list[str] = []

        if not observations:
            gaps.append("No hay observaciones suficientes para interpretar el estado interno.")
            questions.append("¿Qué experiencia concreta originó este estado?")
            actions.append("collect_more_experience")

        if state.novelty >= 0.6 and state.confidence < 0.7:
            gaps.append("La novedad supera la confianza disponible.")
            questions.append("¿Qué parte de lo observado es nueva y qué evidencia falta para comprenderla?")
            hypotheses.append("La señal novedosa puede contener un patrón útil aún no verificado.")
            actions.append("investigate_novelty")

        if state.curiosity >= 0.55:
            questions.append("¿Por qué este patrón atrae atención y con qué conocimiento previo se relaciona?")
            actions.append("compare_with_memory")

        if contradictions:
            gaps.append("Existen interpretaciones incompatibles dentro del mismo flujo Qualia.")
            questions.append("¿Qué evidencia independiente permite resolver la contradicción?")
            hypotheses.append("Al menos una interpretación actual es incompleta o depende de contexto ausente.")
            actions.append("request_independent_verification")

        if learnings and not evidence_refs:
            gaps.append("Hay aprendizaje propuesto sin referencias de evidencia.")
            questions.append("¿De dónde proviene esta conclusión y cómo puede falsarse?")
            actions.append("quarantine_unreferenced_learning")

        if patterns and not learnings:
            questions.append("¿Este patrón merece convertirse en una hipótesis de aprendizaje?")
            actions.append("form_learning_hypothesis")

        if not questions:
            questions.append("¿Qué cambió en el sistema después de esta experiencia?")
            actions.append("observe_change_over_time")

        confidence = self._bounded((state.confidence + state.coherence) / 2.0)
        curiosity = self._bounded(max(state.curiosity, state.novelty, 0.35 if gaps else 0.0))

        return IntrospectionReport(
            run_id=run_id,
            trigger=self._trigger(state, contradictions, gaps),
            observed_state=state.to_dict(),
            observations=observations[:12],
            contradictions=contradictions,
            knowledge_gaps=gaps,
            self_questions=self._unique(questions),
            hypotheses=self._unique(hypotheses),
            recommended_actions=self._unique(actions),
            confidence=confidence,
            curiosity=curiosity,
            requires_verification=bool(gaps or contradictions or hypotheses),
            status="hypothesis",
            evidence_refs=evidence_refs,
        )

    @staticmethod
    def _as_dict(item: NeuronExperience | dict[str, Any]) -> dict[str, Any]:
        if isinstance(item, NeuronExperience):
            return item.to_dict()
        return dict(item)

    @staticmethod
    def _bounded(value: float) -> float:
        return round(max(0.0, min(1.0, float(value))), 4)

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        return list(dict.fromkeys(item for item in items if item))

    @staticmethod
    def _trigger(state: QualiaState, contradictions: list[str], gaps: list[str]) -> str:
        if contradictions:
            return "contradiction"
        if state.novelty >= 0.6:
            return "novelty"
        if gaps:
            return "knowledge_gap"
        if state.curiosity >= 0.55:
            return "curiosity"
        return "routine_reflection"

    @staticmethod
    def _detect_contradictions(rows: list[dict[str, Any]]) -> list[str]:
        claims: dict[str, set[str]] = {}
        for row in rows:
            subject = str(row.get("mission") or row.get("source") or "general").strip().lower()
            observation = str(row.get("observation", "")).strip().lower()
            if not observation:
                continue
            polarity = "negative" if any(token in observation for token in (" no ", "nunca", "falso", "incorrecto", "falló", "falla")) else "positive"
            claims.setdefault(subject, set()).add(polarity)

        contradictions = []
        for subject, polarities in claims.items():
            if {"positive", "negative"}.issubset(polarities):
                contradictions.append(f"Observaciones de polaridad opuesta sobre: {subject}.")
        return contradictions
