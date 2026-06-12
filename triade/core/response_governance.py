"""Compuertas de coherencia, deduplicación y continuidad de respuesta."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _normalize(text: str) -> str:
    return _SPACE_RE.sub(" ", text.strip().lower())


def _split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]


def _dedupe_consecutive(items: list[str]) -> tuple[list[str], int]:
    cleaned: list[str] = []
    removed = 0
    for item in items:
        if cleaned and _normalize(cleaned[-1]) == _normalize(item):
            removed += 1
            continue
        cleaned.append(item)
    return cleaned, removed


def _recent_response_from_history(conversation_history: Any) -> str:
    if not isinstance(conversation_history, list):
        return ""
    for item in reversed(conversation_history):
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        content = str(item.get("content") or "").strip()
        if role in {"bot", "assistant", "assistant_final"} and content:
            return content
    return ""


@dataclass(slots=True)
class ContinuityResult:
    status: str
    topic: str | None = None
    previous_topic: str | None = None
    is_follow_up: bool = False
    next_step: str | None = None
    trace: dict[str, Any] = field(default_factory=dict)


class ConversationContinuityService:
    """Detecta continuidad entre el input actual y el contexto reciente."""

    def analyze(
        self,
        *,
        user_input: str,
        conversation_history: Any = None,
        previous_response: str = "",
    ) -> ContinuityResult:
        history_response = _recent_response_from_history(conversation_history)
        last_response = previous_response or history_response
        topic = self._topic(user_input)
        previous_topic = self._topic(last_response)
        similarity = SequenceMatcher(None, _normalize(user_input), _normalize(last_response)).ratio() if last_response else 0.0
        is_follow_up = bool(last_response) and (similarity >= 0.55 or self._follow_up_hint(user_input))
        next_step = None
        if is_follow_up and topic:
            next_step = f"Ya habíamos identificado {topic}; ahora toca avanzar con el siguiente paso."
        elif is_follow_up:
            next_step = "Ya habíamos identificado el punto principal; ahora toca avanzar con el siguiente paso."
        return ContinuityResult(
            status="ok",
            topic=topic,
            previous_topic=previous_topic,
            is_follow_up=is_follow_up,
            next_step=next_step,
            trace={
                "conversation_history_used": bool(conversation_history),
                "history_response_found": bool(history_response),
                "similarity_to_previous_response": round(similarity, 4),
            },
        )

    @staticmethod
    def _topic(text: str) -> str | None:
        text = text.strip()
        if not text:
            return None
        words = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9_-]+", text) if len(w) >= 4]
        if not words:
            return None
        return " ".join(words[:4]).strip()

    @staticmethod
    def _follow_up_hint(text: str) -> bool:
        lowered = text.lower()
        return any(
            token in lowered
            for token in (
                "y ahora",
                "seguimiento",
                "continuar",
                "más detalle",
                "mas detalle",
                "retoma",
                "retomar",
                "acerca de eso",
            )
        )


@dataclass(slots=True)
class CoherenceResult:
    response_final: str
    coherence_status: str
    corrections_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


class ResponseCoherenceGate:
    """Corrige contradicciones entre safety, memoria, qualia y salida preliminar."""

    def apply(
        self,
        *,
        user_input: str,
        intent: str | None,
        risk: str | None,
        crystal_temporal_status: str | None,
        safety: Any,
        memory_recall: dict[str, Any] | None,
        neuron_contribution_summary: dict[str, Any] | None,
        qualia_hypothesis: dict[str, Any] | None,
        output_preliminary: str,
        verification_report: Any | None = None,
        continuity: ContinuityResult | None = None,
    ) -> CoherenceResult:
        response = str(output_preliminary or "").strip()
        warnings: list[str] = []
        corrections: list[str] = []
        trace: dict[str, Any] = {
            "intent": intent,
            "risk": risk,
            "crystal_temporal_status": crystal_temporal_status,
            "safety_status": getattr(safety, "status", None),
            "continuity": continuity.trace if continuity else {},
            "verification_status": getattr(verification_report, "status", None) if verification_report is not None else None,
        }

        safety_status = str(getattr(safety, "status", "") or "")
        safety_reason = str(getattr(safety, "reason", "") or "")
        human_required = bool(getattr(safety, "human_approval_required", False))
        risk_level = str(getattr(safety, "risk_level", risk or "") or "")

        if safety_status == "blocked":
            response = "La acción fue bloqueada por Safety."
            corrections.append("safety_block_override")
        elif safety_status in {"sandbox_only", "requires_human_approval"} or human_required:
            if "aprobación humana" not in response.lower():
                response = f"{response}\n\nSe requiere aprobación humana antes de ejecutar la acción."
                corrections.append("human_approval_added")
        elif risk_level in {"high", "critical"} and "cautel" not in response.lower():
            response = f"{response}\n\nLa respuesta debe tratarse con cautela por el riesgo detectado."
            corrections.append("risk_caution_added")

        memory = memory_recall or {}
        authorized_matches = memory.get("authorized_matches") or memory.get("semantic_matches") or []
        memory_confidence = float(memory.get("confidence") or 0.0)
        if not authorized_matches or memory_confidence < 0.55:
            if any(phrase in response.lower() for phrase in ("según memoria", "segun memoria", "recuerdo", "sé que", "se que")):
                response = response.replace("Según memoria", "No hay evidencia suficiente en memoria consolidada para afirmar")
                response = response.replace("Segun memoria", "No hay evidencia suficiente en memoria consolidada para afirmar")
                response = response.replace("sé que", "no tengo evidencia suficiente para afirmar")
                response = response.replace("se que", "no tengo evidencia suficiente para afirmar")
                corrections.append("memory_evidence_downgraded")
            warnings.append("Memoria insuficiente o sin matches autorizados para afirmar hechos estables.")

        if qualia_hypothesis and qualia_hypothesis.get("status") == "available":
            if "qualia" in response.lower() and "hipótesis" not in response.lower() and "hipotesis" not in response.lower():
                response = f"{response}\n\nLo de Qualia se trata como hipótesis, no como memoria estable."
                corrections.append("qualia_marked_hypothesis")

        if neuron_contribution_summary:
            if neuron_contribution_summary.get("blocked"):
                warnings.append("Hubo contribuciones neuronales bloqueadas por policy.")
            if neuron_contribution_summary.get("ignored"):
                warnings.append("Hubo contribuciones neuronales ignoradas por riesgo, confianza o safety.")

        if continuity and continuity.is_follow_up and continuity.next_step:
            if _normalize(continuity.next_step) not in _normalize(response):
                response = f"{response}\n\n{continuity.next_step}"
                corrections.append("continuity_next_step_added")

        if verification_report is not None:
            trace["verification_warnings"] = getattr(verification_report, "warnings", [])
            trace["verification_errors"] = getattr(verification_report, "errors", [])

        status = "ok"
        if corrections:
            status = "corrected"
        if safety_status == "blocked":
            status = "blocked"
        elif any("contrad" in warning.lower() for warning in warnings):
            status = "needs_review"

        trace["safety_reason"] = safety_reason
        trace["memory_matches"] = len(authorized_matches) if isinstance(authorized_matches, list) else 0

        return CoherenceResult(
            response_final=response.strip(),
            coherence_status=status,
            corrections_applied=corrections,
            warnings=warnings,
            trace=trace,
        )


@dataclass(slots=True)
class DedupResult:
    deduplicated_response: str
    repeated_blocks_removed: int
    similarity_to_recent_response: float
    action: str
    trace: dict[str, Any] = field(default_factory=dict)


class ResponseDeduplicationGate:
    """Elimina repetición literal y refuerza continuidad con el episodio previo."""

    def apply(
        self,
        *,
        response: str,
        recent_response: str = "",
        continuity: ContinuityResult | None = None,
    ) -> DedupResult:
        raw = str(response or "").strip()
        paragraphs = _split_paragraphs(raw)
        deduped_paragraphs, removed = self._dedupe_paragraphs(paragraphs)
        deduped_text = "\n\n".join(deduped_paragraphs).strip()
        similarity = SequenceMatcher(None, _normalize(deduped_text), _normalize(recent_response or "")).ratio() if recent_response else 0.0
        action = "unchanged"

        if removed > 0:
            action = "deduplicated"
        if similarity >= 0.80 and recent_response:
            action = "rewritten_for_progress"
            if continuity and continuity.next_step and continuity.next_step not in deduped_text:
                deduped_text = f"{deduped_text}\n\n{continuity.next_step}" if deduped_text else continuity.next_step
            elif recent_response and deduped_text:
                deduped_text = f"{deduped_text}\n\nYa habíamos identificado el punto principal; ahora toca avanzar con el siguiente paso."

        return DedupResult(
            deduplicated_response=deduped_text.strip(),
            repeated_blocks_removed=removed,
            similarity_to_recent_response=round(similarity, 4),
            action=action,
            trace={
                "paragraphs_in": len(paragraphs),
                "paragraphs_out": len(deduped_paragraphs),
            },
        )

    @staticmethod
    def _dedupe_paragraphs(paragraphs: list[str]) -> tuple[list[str], int]:
        cleaned: list[str] = []
        removed = 0
        seen: set[str] = set()
        for paragraph in paragraphs:
            key = _normalize(paragraph)
            if key in seen:
                removed += 1
                continue
            seen.add(key)
            cleaned.append(paragraph)
        cleaned, consecutive_removed = _dedupe_consecutive(cleaned)
        return cleaned, removed + consecutive_removed

