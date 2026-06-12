"""Compuerta de coherencia para la respuesta final del runner.

Evita reutilizar la respuesta previa cuando el input actual es feedback,
agradecimiento o cierre, y distingue seguimiento real de cambio de contexto.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\sáéíóúüñ¿?¡!]")

POSITIVE_FEEDBACK_PHRASES = (
    "muy bien",
    "muy bine",
    "felicitaciones",
    "excelente",
    "perfecto",
    "bien hecho",
    "buen trabajo",
    "genial",
)

THANKS_PHRASES = (
    "gracias",
    "muchas gracias",
    "ok gracias",
    "ok, gracias",
    "thanks",
)

ACKNOWLEDGEMENT_PHRASES = (
    "ok",
    "bien",
    "listo",
    "entendido",
    "vale",
    "de acuerdo",
)

CORRECTION_PHRASES = (
    "quise decir",
    "corrijo",
    "me refiero a",
    "no, me refiero",
    "no, quería decir",
    "no, queria decir",
)

QUESTION_WORDS = (
    "que",
    "qué",
    "cual",
    "cuál",
    "como",
    "cómo",
    "cuando",
    "cuándo",
    "donde",
    "dónde",
    "quien",
    "quién",
    "cuanto",
    "cuánto",
)

FOLLOW_UP_HINTS = (
    "y ",
    "y?",
    "ademas",
    "además",
    "explícame más",
    "explicame más",
    "explicame mas",
    "más detalle",
    "mas detalle",
    "sobre eso",
    "respecto a eso",
)


def evaluate_response_coherence(
    user_input: str,
    proposed_response: str,
    previous_user_input: str | None = None,
    previous_response: str | None = None,
    intent: str | None = None,
    memory_context: dict[str, Any] | None = None,
    neuron_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = _normalize(user_input)
    response = str(proposed_response or "").strip()
    previous_user = _normalize(previous_user_input or "")
    previous_answer = str(previous_response or "").strip()
    memory_context = memory_context or {}
    neuron_context = neuron_context or {}

    detected_input_type = _detect_input_type(text, previous_user)
    should_reuse_previous_answer = detected_input_type == "follow_up"
    should_acknowledge_feedback = detected_input_type in {"positive_feedback", "thanks", "acknowledgement", "emotional_feedback"}
    should_answer_factually = detected_input_type in {"factual_question", "follow_up", "command", "new_topic"}

    repeated_previous_answer = bool(previous_answer) and _response_repeats_previous_answer(response, previous_answer)
    coherence_score = _base_score(detected_input_type, response, previous_answer, memory_context, neuron_context)
    warnings: list[str] = []
    reason = "coherent"
    status = "ok"
    final_response = response

    if detected_input_type in {"positive_feedback", "thanks", "acknowledgement", "emotional_feedback"}:
        final_response = _acknowledge_feedback(detected_input_type)
        status = "rewritten"
        reason = "feedback_acknowledged_without_repeating_previous_answer"
        should_reuse_previous_answer = False
        should_answer_factually = False
        if repeated_previous_answer:
            status = "blocked"
            reason = "blocked_repeated_previous_answer_for_feedback_input"
            coherence_score = min(coherence_score, 0.18)
        elif detected_input_type == "thanks":
            coherence_score = max(coherence_score, 0.92)
        else:
            coherence_score = max(coherence_score, 0.88)

    elif detected_input_type == "correction":
        final_response = _acknowledge_correction(previous_answer)
        status = "rewritten"
        reason = "correction_applied_without_repeating_previous_answer"
        should_reuse_previous_answer = False
        should_answer_factually = False
        coherence_score = max(coherence_score, 0.80)

    elif detected_input_type == "follow_up":
        if repeated_previous_answer and previous_answer:
            coherence_score = min(coherence_score, 0.48)
            warnings.append("Proposed response repeated the previous answer; follow-up should advance context.")
            reason = "follow_up_requires_progress_not_repetition"
            status = "blocked" if _looks_like_stuck_repetition(response, previous_answer) else "rewritten"
            final_response = _follow_up_progress_response(response, previous_answer, previous_user)
        else:
            coherence_score = max(coherence_score, 0.84)
            final_response = response or _follow_up_progress_response(response, previous_answer, previous_user)

    elif detected_input_type == "factual_question":
        if repeated_previous_answer and previous_answer:
            warnings.append("Response repeated the previous answer for a factual question.")
            coherence_score = min(coherence_score, 0.52)
            reason = "blocked_repeated_previous_answer_for_new_question"
            status = "blocked"
            final_response = response or previous_answer
        else:
            coherence_score = max(coherence_score, 0.90)

    elif detected_input_type == "command":
        coherence_score = max(coherence_score, 0.78)

    elif detected_input_type == "new_topic":
        if repeated_previous_answer and previous_answer:
            coherence_score = min(coherence_score, 0.45)
            status = "blocked"
            reason = "blocked_repeated_previous_answer_for_new_topic"
            final_response = _new_topic_response(response)
        else:
            coherence_score = max(coherence_score, 0.80)

    else:
        if repeated_previous_answer and previous_answer:
            coherence_score = min(coherence_score, 0.50)
            warnings.append("Low-confidence coherence: response resembles the previous answer.")
            status = "blocked"
            reason = "blocked_repeated_previous_answer_for_unclear_input"
            final_response = _fallback_response(text, previous_answer)
        else:
            coherence_score = max(coherence_score, 0.65)

    if should_acknowledge_feedback and not final_response:
        final_response = _acknowledge_feedback(detected_input_type)

    final_response = _clean_final_response(final_response)
    if detected_input_type in {"positive_feedback", "thanks", "acknowledgement", "emotional_feedback"}:
        final_response = _ensure_no_previous_answer(final_response, previous_answer)

    if previous_answer and final_response and _response_repeats_previous_answer(final_response, previous_answer) and detected_input_type != "follow_up":
        if detected_input_type in {"positive_feedback", "thanks", "acknowledgement", "emotional_feedback"}:
            final_response = _acknowledge_feedback(detected_input_type)
            status = "blocked" if repeated_previous_answer else "rewritten"
            reason = "blocked_repeated_previous_answer_for_feedback_input"
        else:
            final_response = _fallback_response(text, previous_answer)
            status = "blocked"
            reason = "blocked_repeated_previous_answer_for_feedback_input" if should_acknowledge_feedback else reason

    return {
        "status": status,
        "detected_input_type": detected_input_type,
        "should_reuse_previous_answer": should_reuse_previous_answer,
        "should_answer_factually": should_answer_factually,
        "should_acknowledge_feedback": should_acknowledge_feedback,
        "reason": reason,
        "coherence_score": round(float(max(0.0, min(1.0, coherence_score))), 3),
        "final_response": final_response or None,
        "warnings": warnings,
        "trace": {
            "intent": intent,
            "previous_user_input": previous_user_input or "",
            "previous_response_present": bool(previous_answer),
            "memory_context_keys": sorted(list(memory_context.keys()))[:12],
            "neuron_context_keys": sorted(list(neuron_context.keys()))[:12],
            "repeated_previous_answer": repeated_previous_answer,
        },
    }


def _normalize(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").strip().lower())


def _strip_accents(text: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _detect_input_type(text: str, previous_user: str = "") -> str:
    if not text:
        return "unclear"
    plain = _strip_accents(text)
    if any(phrase in text for phrase in CORRECTION_PHRASES) or any(phrase in plain for phrase in CORRECTION_PHRASES):
        return "correction"
    if any(phrase == text or phrase in text for phrase in THANKS_PHRASES):
        return "thanks"
    if any(phrase == text or phrase in text for phrase in ACKNOWLEDGEMENT_PHRASES):
        if len(text.split()) <= 3 or plain.startswith(("ok ", "vale ", "listo ")):
            return "acknowledgement"
    if plain.startswith(("ok ", "vale ", "listo ")) and any(phrase in text for phrase in POSITIVE_FEEDBACK_PHRASES):
        return "acknowledgement"
    if any(phrase == text or phrase in text for phrase in POSITIVE_FEEDBACK_PHRASES):
        return "positive_feedback"
    if _looks_like_follow_up(text, previous_user):
        return "follow_up"
    if _looks_like_question(text):
        return "factual_question"
    if _looks_like_command(text):
        return "command"
    if _looks_like_emotional_feedback(text):
        return "emotional_feedback"
    if _looks_like_new_topic(text, previous_user):
        return "new_topic"
    if len(text.split()) <= 3:
        return "unclear"
    return "new_topic"


def _looks_like_question(text: str) -> bool:
    plain = _strip_accents(text)
    if "?" in text:
        return True
    return any(token in plain.split()[:4] for token in QUESTION_WORDS) or plain.startswith(("que ", "como ", "cuando ", "donde ", "quien ", "cual ", "cuanto "))


def _looks_like_follow_up(text: str, previous_user: str) -> bool:
    plain = _strip_accents(text)
    prev = _strip_accents(previous_user)
    if not prev:
        return False
    if any(hint in plain for hint in FOLLOW_UP_HINTS) and _looks_like_question(text):
        return True
    if plain.startswith("y ") and _looks_like_question(text):
        return True
    prev_tokens = set(re.findall(r"[a-z0-9]+", prev))
    current_tokens = set(re.findall(r"[a-z0-9]+", plain))
    overlap = len(prev_tokens & current_tokens)
    return _looks_like_question(text) and overlap >= 1


def _looks_like_command(text: str) -> bool:
    plain = _strip_accents(text)
    return plain.startswith(("crea ", "haz ", "dame ", "muestra ", "explica ", "registra ", "necesito "))


def _looks_like_emotional_feedback(text: str) -> bool:
    plain = _strip_accents(text)
    return any(term in plain for term in ("felicit", "bien hecho", "excelente", "genial", "muy bien", "muy bine"))


def _looks_like_new_topic(text: str, previous_user: str) -> bool:
    if not previous_user:
        return False
    plain = _strip_accents(text)
    prev = _strip_accents(previous_user)
    if not plain or not prev:
        return False
    similarity = SequenceMatcher(None, plain, prev).ratio()
    return similarity < 0.35 and len(plain.split()) >= 3


def _response_repeats_previous_answer(response: str, previous_response: str) -> bool:
    if not response or not previous_response:
        return False
    normalized_response = _normalize(response)
    normalized_previous = _normalize(previous_response)
    if normalized_previous in normalized_response:
        return True
    similarity = SequenceMatcher(None, normalized_response, normalized_previous).ratio()
    return similarity >= 0.72


def _looks_like_stuck_repetition(response: str, previous_response: str) -> bool:
    if not response or not previous_response:
        return False
    return _response_repeats_previous_answer(response, previous_response) and len(response.split()) <= len(previous_response.split()) + 12


def _acknowledge_feedback(detected_input_type: str) -> str:
    if detected_input_type == "thanks":
        return "De nada. Seguimos."
    if detected_input_type == "acknowledgement":
        return "Perfecto. Queda registrado."
    if detected_input_type == "emotional_feedback":
        return "Gracias. Registro tu feedback y sigo afinando la Tríade."
    return "Gracias. Registro tu feedback positivo y seguimos afinando la Tríade."


def _acknowledge_correction(previous_response: str) -> str:
    if previous_response:
        return "Entendido. Corrijo el contexto y sigo desde la aclaración."
    return "Entendido. Corrijo el contexto."


def _follow_up_progress_response(response: str, previous_response: str, previous_user: str) -> str:
    if response:
        return response
    if previous_response:
        return previous_response
    if previous_user:
        return "Entendido. Retomo el contexto anterior para responder con precisión."
    return "Entendido. Continúo con el contexto previo."


def _new_topic_response(response: str) -> str:
    if response:
        return response
    return "Entendido. Cambio de contexto registrado."


def _fallback_response(user_input: str, previous_response: str) -> str:
    if previous_response:
        return "Entendido. Cambio de contexto registrado."
    if user_input:
        return "Entendido."
    return "Recibido."


def _base_score(
    detected_input_type: str,
    response: str,
    previous_response: str,
    memory_context: dict[str, Any],
    neuron_context: dict[str, Any],
) -> float:
    score = {
        "positive_feedback": 0.94,
        "thanks": 0.95,
        "acknowledgement": 0.90,
        "emotional_feedback": 0.88,
        "factual_question": 0.89,
        "follow_up": 0.86,
        "correction": 0.84,
        "command": 0.79,
        "new_topic": 0.76,
        "unclear": 0.60,
    }.get(detected_input_type, 0.70)
    if previous_response and _response_repeats_previous_answer(response, previous_response):
        score -= 0.35
    if memory_context.get("qualia_bus"):
        score += 0.02
    if neuron_context.get("mission_id") is not None:
        score += 0.01
    return score


def _clean_final_response(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", str(text or "").strip())


def _ensure_no_previous_answer(text: str, previous_response: str) -> str:
    if not previous_response:
        return text
    if _response_repeats_previous_answer(text, previous_response):
        return "Gracias. Registro tu feedback positivo y seguimos afinando la Tríade."
    return text
