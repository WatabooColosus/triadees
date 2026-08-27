"""Compuerta para decidir si un input merece crear una neurona.

La compuerta evita literalismos:
- preguntas factuales simples se tratan como aprendizaje o memoria episódica;
- feedback positivo / agradecimiento solo alimenta Qualia;
- neuronas solo nacen cuando hay necesidad operativa repetible o petición explícita.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

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

POSITIVE_FEEDBACK = (
    "muy bien",
    "muy bine",
    "felicitaciones",
    "excelente",
    "perfecto",
    "bien hecho",
    "buen trabajo",
    "genial",
)

THANKS = (
    "gracias",
    "muchas gracias",
    "ok gracias",
    "ok, gracias",
    "thanks",
)

#: `gracias a X` es causal, no un agradecimiento.
#:
#: Medido sobre un input real: «Dime una cosa concreta que hayas aprendido
#: **gracias a** nuestras conversaciones…» se clasificaba como `thanks` y el
#: sistema contestaba «De nada. Seguimos.» La comparación era por subcadena, y
#: en castellano `gracias a` es una locución preposicional causal que no tiene
#: nada que ver con agradecer.
#:
#: La excepción de la excepción: `gracias a ti`, `gracias a vosotros`,
#: `gracias a todos` sí agradecen. Se listan porque el complemento es una
#: persona, no una causa.
_GRACIAS_CAUSAL = re.compile(r"\bgracias\s+a\s+(?!ti\b|vos\b|vosotros\b|usted|todos\b)")

#: Un agradecimiento es corto. Una petición larga que menciona `gracias` por el
#: medio es una petición, no un agradecimiento: sin este tope bastaba con que la
#: palabra apareciera en cualquier parte de un párrafo entero.
_MAX_PALABRAS_AGRADECIMIENTO = 8

#: Marcas de pregunta operativa o introspectiva. No son «temas»: son señales de
#: que la respuesta exige mirar el estado real del sistema, no recuperar un dato.
#:
#: Medido sobre inputs reales: «¿Qué le falta a una neurona para pasar a
#: funcional?» y «¿Qué mejora deberías realizar?» acababan en `factual_simple`
#: sólo por empezar con «qué», y con ello en `score=0.15` y la ruta de
#: aprendizaje trivial. La heurística no miraba de qué se preguntaba.
OPERATIONAL_QUESTION_HINTS = (
    "que le falta",
    "que falta",
    "deberias",
    "deberia",
    "justifique",
    "justifica",
    "evidencia",
    "criterios",
    "criterio",
    "compara",
    "contradictor",
    "compatibles",
    "diagnostico",
    "propon",
    "propuesta",
    "mejora",
    "canary",
    "lora",
    "peft",
    "federad",
    "gobernad",
    "promover",
    "promocion",
    "funcional",
    "objetivo",
    "subobjetivo",
    "neurona",
    "aprendido",
    "aprendiste",
    "por que",
    "explicame",
    "explica",
    "demuestra",
)

ACKNOWLEDGEMENT = (
    "ok",
    "perfecto",
    "bien",
    "listo",
    "entendido",
    "vale",
    "de acuerdo",
)

EXPLICIT_CREATE_HINTS = (
    "crea una neurona",
    "crear una neurona",
    "necesito una neurona",
    "quiero una neurona",
    "implementa una neurona",
    "diseña una neurona",
    "propón una neurona",
    "propon una neurona",
    "hace una neurona",
    "haz una neurona",
)

MINOR_CORRECTION_HINTS = (
    "quise decir",
    "corrijo",
    "me refiero a",
    "no, me refiero",
    "no, quería decir",
    "no, queria decir",
)

OPERATIONAL_NEED_HINTS = (
    "auditar",
    "audita",
    "evitar contradicciones",
    "memoria",
    "repetible",
    "operacional",
    "producción",
    "produccion",
    "mantenimiento",
    "automatizar",
    "soporte",
    "monitoreo",
    "diagnosticar",
    "diagnóstico",
)


def evaluate_neuron_candidate_worthiness(
    user_input: str,
    intent: str,
    domain: str | None = None,
    response: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = _normalize(user_input)
    plain = _strip_accents(text)
    context = context or {}

    detected_type = _detect_type(text)
    explicit_create = _looks_like_explicit_create(text, intent, context)
    operational_need = _looks_like_operational_need(text, intent, domain, context)
    factual_simple = _looks_like_factual_simple(text)
    operational_question = detected_type == "operational_question"
    feedback_like = detected_type in {
        "positive_feedback",
        "thanks",
        "acknowledgement",
        "emotional_feedback",
    }
    correction_like = detected_type == "correction"
    short_casual = (
        len(text.split()) <= 4 and not explicit_create and not operational_need
    )

    route = "ignore"
    should_create_neuron = False
    score = 0.0
    reason = "no_operational_need_detected"
    suggested_name: str | None = None
    suggested_domain = _suggest_domain(domain, intent, context)
    required_evidence: list[str] = []

    if explicit_create and (operational_need or factual_simple is False):
        should_create_neuron = True
        route = "neuron"
        score = 0.86 if operational_need else 0.80
        reason = "explicit_neuron_request_with_operational_scope"
        suggested_name = _suggested_name(text, suggested_domain, context)
        required_evidence = [
            "repeated_operational_need",
            "run_traceability",
            "domain_specific_evidence",
        ]
    elif factual_simple:
        route = "learning_candidate"
        score = 0.15
        reason = "factual_simple_question_should_not_create_neuron"
        suggested_name = None
        required_evidence = ["episodic_memory", "later_recurrence"]
    elif feedback_like:
        route = "qualia_feedback"
        score = 0.02
        reason = "feedback_should_be_recorded_not_converted_to_neuron"
        required_evidence = ["qualia_feedback"]
    elif correction_like:
        route = "episodic_memory"
        score = 0.12
        reason = "minor_correction_should_update_context_not_create_neuron"
        required_evidence = ["correction_trace"]
    elif operational_question:
        # Una pregunta sobre el estado real del sistema no crea neurona, pero
        # tampoco es trivial: se conserva como candidata de aprendizaje con el
        # peso que le corresponde. Antes caía en la rama `factual_simple` con
        # 0.15 y el motivo «no debería crear neurona», que era cierto y a la vez
        # engañoso: describía mal por qué.
        route = "learning_candidate"
        score = 0.45
        reason = "operational_question_needs_system_state_not_a_new_neuron"
        required_evidence = ["runtime_evidence", "later_recurrence"]
    elif operational_need:
        route = "learning_candidate"
        score = 0.62
        reason = "operational_need_detected_but_not_strong_enough_for_neuron"
        required_evidence = ["repeated_operational_need", "runtime_evidence"]
    elif short_casual:
        route = "ignore"
        score = 0.04
        reason = "short_casual_input_has_no_neuron_worthiness"
        required_evidence = ["none"]
    else:
        route = "learning_candidate"
        score = 0.25
        reason = "unclear_input_should_be_kept_as_learning_or_memory_candidate"
        required_evidence = ["later_recurrence"]

    if not suggested_name and should_create_neuron:
        suggested_name = _suggested_name(text, suggested_domain, context)

    return {
        "should_create_neuron": should_create_neuron,
        "route": route,
        "reason": reason,
        "score": round(max(0.0, min(1.0, score)), 3),
        "detected_type": detected_type,
        "suggested_name": suggested_name,
        "suggested_domain": suggested_domain,
        "required_evidence": required_evidence,
        "trace": {
            "explicit_create": explicit_create,
            "operational_need": operational_need,
            "factual_simple": factual_simple,
            "operational_question": operational_question,
            "feedback_like": feedback_like,
            "correction_like": correction_like,
            "plain": plain[:200],
        },
    }


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def _detect_type(text: str) -> str:
    if not text:
        return "unclear"
    plain = _strip_accents(text)
    if any(hint in plain for hint in MINOR_CORRECTION_HINTS):
        return "correction"
    if _is_gratitude(plain):
        return "thanks"
    if any(phrase in plain for phrase in ACKNOWLEDGEMENT) and (
        len(plain.split()) <= 3 or plain.startswith(("ok ", "vale ", "listo "))
    ):
        return "acknowledgement"
    if any(phrase in plain for phrase in POSITIVE_FEEDBACK):
        return "positive_feedback"
    # El orden importa: una pregunta operativa **también** es una pregunta, así
    # que si `_looks_like_question` decidiera primero, toda pregunta caería en
    # `factual_simple` por el mero hecho de serlo. Eso es exactamente lo que
    # pasaba con «¿Qué le falta a una neurona para pasar a funcional?».
    if _looks_like_operational_question(plain):
        return "operational_question"
    if _looks_like_question(plain):
        return "factual_simple"
    if any(hint in plain for hint in EXPLICIT_CREATE_HINTS):
        return "command"
    return "unclear"


def _looks_like_question(plain: str) -> bool:
    if "?" in plain:
        return True
    tokens = plain.split()
    return bool(tokens and tokens[0] in QUESTION_WORDS) or plain.startswith(
        (
            "que ",
            "qué ",
            "como ",
            "cómo ",
            "cuando ",
            "cuándo ",
            "donde ",
            "dónde ",
            "quien ",
            "quién ",
            "cual ",
            "cuál ",
            "cuanto ",
            "cuánto ",
        )
    )


def _looks_like_explicit_create(
    text: str, intent: str, context: dict[str, Any]
) -> bool:
    plain = _strip_accents(text)
    if any(hint in plain for hint in EXPLICIT_CREATE_HINTS):
        return True
    if str(intent).strip().lower() in {
        "build_or_update",
        "create",
        "construct",
        "develop",
    }:
        return True
    context_text = " ".join(
        str(context.get(key) or "")
        for key in ("active_neuron", "project_id", "domain", "goal")
    ).lower()
    return any(
        hint in context_text for hint in ("neuron", "neurona", "build", "create")
    )


def _looks_like_operational_need(
    text: str, intent: str, domain: str | None, context: dict[str, Any]
) -> bool:
    plain = _strip_accents(text)
    if any(hint in plain for hint in OPERATIONAL_NEED_HINTS):
        return True
    if intent in {"build_or_update", "analyze", "memory"} and len(plain.split()) >= 5:
        return True
    if domain and domain not in {"general", "conversation"}:
        return True
    context_text = " ".join(
        str(context.get(key) or "") for key in ("mission", "goal", "project_id")
    ).lower()
    return any(
        hint in context_text for hint in ("auditar", "operacion", "repetible", "neuron")
    )


def _is_gratitude(plain: str) -> bool:
    """¿Agradece, o sólo contiene la palabra?

    Tres condiciones, y las tres hacen falta:

    1. `gracias`/`thanks` como **palabra**, no como subcadena;
    2. que no sea la locución causal `gracias a <algo>`, salvo cuando el
       complemento es una persona (`gracias a ti`);
    3. que el mensaje sea corto. Agradecer es un acto breve; un párrafo que
       menciona `gracias` por el medio está pidiendo otra cosa.
    """
    if not re.search(r"\b(?:gracias|thanks)\b", plain):
        return False
    if _GRACIAS_CAUSAL.search(plain):
        return False
    return len(plain.split()) <= _MAX_PALABRAS_AGRADECIMIENTO


def _looks_like_operational_question(plain: str) -> bool:
    """Pregunta que exige mirar el estado real del sistema, no recuperar un dato.

    No se decide por longitud ni por la palabra inicial: se decide por lo que
    se pregunta. «¿Cuál es la capital de Francia?» empieza igual que «¿Cuál es
    la evidencia que exigirías antes de promover la neurona?» y no son la misma
    clase de pregunta.
    """
    if not _looks_like_question(plain):
        return False
    return any(hint in plain for hint in OPERATIONAL_QUESTION_HINTS)


def _looks_like_factual_simple(text: str) -> bool:
    plain = _strip_accents(text)
    if not _looks_like_question(plain):
        return False
    # Una pregunta operativa no es factual simple aunque sea corta y aunque
    # empiece por una palabra interrogativa. Esta comprobación va **antes** que
    # el conteo de tokens justamente porque el conteo daba `True` a todo lo
    # corto, y «¿Qué mejora deberías realizar?» tiene cinco palabras.
    if _looks_like_operational_question(plain):
        return False
    tokens = [token for token in re.findall(r"[a-z0-9áéíóúüñ]+", plain) if token]
    if len(tokens) <= 10:
        return True
    return bool(any(token in tokens[:3] for token in QUESTION_WORDS))


def _suggest_domain(domain: str | None, intent: str, context: dict[str, Any]) -> str:
    if domain and str(domain).strip():
        return str(domain).strip()
    ctx_domain = str(context.get("domain") or "").strip()
    if ctx_domain:
        return ctx_domain
    if intent in {"build_or_update", "create"}:
        return "system_governance"
    return "general"


def _suggested_name(text: str, domain: str, context: dict[str, Any]) -> str:
    context_name = str(
        context.get("active_neuron") or context.get("project_id") or ""
    ).strip()
    if context_name:
        return context_name
    keywords = _extract_keywords(text)
    if not keywords:
        return f"neurona-{domain.replace('_', '-')}"
    return "neurona-" + "-".join(keywords[:4])


def _extract_keywords(text: str) -> list[str]:
    plain = _strip_accents(text)
    tokens = [token for token in re.findall(r"[a-z0-9]+", plain) if len(token) >= 4]
    filtered = [
        token
        for token in tokens
        if token
        not in {
            "crea",
            "crear",
            "neurona",
            "para",
            "una",
            "unas",
            "unos",
            "esto",
            "esta",
            "este",
        }
    ]
    seen: set[str] = set()
    out: list[str] = []
    for token in filtered:
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out
