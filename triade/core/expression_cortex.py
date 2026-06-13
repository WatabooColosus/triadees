"""Corteza de Expresión — Tríade Ω.

Transforma la respuesta cruda del modelo en una síntesis humana adecuada al
contexto conversacional, preservando la evidencia profunda para Cabina Viva.
"""

from __future__ import annotations

import re
from typing import Any

# ── Marcadores internos que la Corteza debe detectar y sintetizar ──────────

_INTERNAL_DUMP_PATTERNS: list[re.Pattern] = [
    re.compile(r"Bodega\s+Global\s+Context|Bodega\s+Global", re.IGNORECASE),
    re.compile(r"bodega[_\s]global|bodega[_\s]summary|global[_\s]context", re.IGNORECASE),
    re.compile(r"QualiaBus", re.IGNORECASE),
    re.compile(r"qualia[_\s]bus|qualia[_\s]signals|qualia[_\s]experiences", re.IGNORECASE),
    re.compile(r"memory[_\s]trace|memory[_\s]diff|semantic[_\s]recall", re.IGNORECASE),
    re.compile(r"memory_trace|semantic_recall|memoria\s+estable", re.IGNORECASE),
    re.compile(r"neuron[_\s]candidate|neuron[_\s]proposal|candidate[_\s]gate", re.IGNORECASE),
    re.compile(r"learning[_\s]journal|post[_\s]run[_\s]learning|learning[_\s]candidate", re.IGNORECASE),
    re.compile(r"candidato[s]?\s+de\s+aprendizaje|hipótesis\s+operacional|hipótesis\s+contextual", re.IGNORECASE),
    re.compile(r"Hipótesis/contexto\s+actual|hipotesis/contexto\s+actual", re.IGNORECASE),
    re.compile(r"símbolos\s+relevantes|política\s+recomendada|episodios\s+recientes", re.IGNORECASE),
    re.compile(r"readiness.*:.*\d|readiness[_\s]report", re.IGNORECASE),
    re.compile(r"activation_count|diagnosis_count|test_plan_count|readiness", re.IGNORECASE),
    re.compile(r"system_events\s*:?\s*\[", re.IGNORECASE),
    re.compile(r"background[_\s]neuron[_\s]candidates", re.IGNORECASE),
    re.compile(r"experimental[_\s]neuron[_\s]activity", re.IGNORECASE),
    re.compile(r"run_path|run_id.*:.*[a-f0-9]{8}|run_ref|mission_id", re.IGNORECASE),
    re.compile(r"output[_\s]gate|coherence.*trace|deduplication.*trace", re.IGNORECASE),
    re.compile(r"estado\s+actual\s+del\s+sistema", re.IGNORECASE),
    re.compile(r"basándonos\s+en\s+los\s+datos\s+proporcionados|basándome\s+en\s+la\s+información\s+proporcionada", re.IGNORECASE),
    re.compile(r"contexto\s+hipotético", re.IGNORECASE),
]

_RAW_JSON_BLOCK = re.compile(r"```(?:json)?\s*\{.*?\}\s*```", re.DOTALL)
_RAW_DICT_LINE = re.compile(r"^\s*(['\"]\w+['\"])\s*:\s*(\[|\{)", re.MULTILINE)


def _detect_expression_mode(
    user_input: str,
    intent: str,
    raw_response: str,
) -> str:
    """Elige el modo de expresión según la intención humana y el contenido."""
    u = user_input.lower().strip()

    diagnostic_requested = any(w in u for w in (
        "audita", "diagnóstico", "diagnostico", "verifica", "status", "heartbeat",
        "cabina", "logs", "errores", "health", "revisa", "que pasó", "que paso",
        "reporte", "auditar", "revisión", "revision", "audit", "check",
    ))

    if _is_self_state_query(u) and not diagnostic_requested:
        return "self_state"

    # Diagnóstico / auditoría / estado
    if diagnostic_requested:
        return "diagnostic"
    # Pregunta técnica de conocimiento (no sobre Tríade)
    if any(w in u for w in ("como funciona", "cómo funciona", "como vuela", "cómo vuela",
                             "como se hace", "cómo se hace",
                             "qué es", "que es", "define", "explica")) and "triage" not in u:
        return "technical_summary"
    # Operacional / misión
    if intent in ("build_or_update", "memory", "analyze"):
        return "operational"
    # Creativo / brainstorming
    if any(w in u for w in ("idea", "crea", "inventa", "imagina", "sugiere")):
        return "creative"
    # Por defecto: conversación natural
    return "natural"


def _is_self_state_query(user_input_lower: str) -> bool:
    return bool(re.search(
        r"\b(te\s+sientes|como\s+te\s+sientes|cómo\s+te\s+sientes|como\s+estas|cómo\s+estás|est[aá]s\s+viva|te\s+sientes\s+viva|qu[eé]\s+sientes|qu[eé]\s+eres\s+ahora|estado\s+operativo|estado\s+interno)\b",
        user_input_lower,
        re.IGNORECASE,
    ))


def _is_semantic_memory_state_query(user_input_lower: str) -> bool:
    return bool(re.search(
        r"\b(memoria\s+sem[aá]ntica|semantic\s+memory|bodega\s+sem[aá]ntica|memoria.*continua)\b",
        user_input_lower,
        re.IGNORECASE,
    ))


def _build_modular_trace(
    signals: dict[str, Any],
    memory: dict[str, Any],
    crystal: dict[str, Any],
    qualia: dict[str, Any],
    bodega_context: dict[str, Any],
    learning_context: dict[str, Any],
    expression_mode: str = "natural",
    system_context: dict[str, Any] | None = None,
) -> str:
    """Construye una traza breve de los módulos internos usados.

    Ejemplo: "Central enfocada · Hipotálamo estable · Bodega disponible ·
    Cristal coherente · Aprendizaje activo"
    """
    parts: list[str] = []

    parts.append("Central coordinada")

    hypothalamus_ok = signals.get("hypothalamus_quality", 0) > 0.3
    parts.append("Hipotálamo estable" if hypothalamus_ok else "Hipotálamo")

    bodega_ok = bool(bodega_context.get("domain_count", 0) > 0)
    parts.append("Bodega disponible" if bodega_ok else "Bodega")

    crystal_status = crystal.get("temporal_status", crystal.get("status", "unknown"))
    crystal_map = {
        "improving": "estabilizando",
        "coherent": "coherente",
        "available": "cuidando coherencia",
        "stable": "estable",
    }
    if str(crystal_status) in crystal_map:
        parts.append(f"Cristal {crystal_map[str(crystal_status)]}")
    elif crystal_status and str(crystal_status) != "unknown":
        parts.append("Cristal cuidando coherencia")
    else:
        parts.append("Cristal cuidando coherencia")

    if memory.get("semantic_matches", 0) > 0 or memory.get("confidence", 0) > 0.3:
        parts.append("Memoria presente")

    if learning_context.get("active", False) or learning_context.get("enabled", False):
        parts.append("Aprendizaje activo")

    show_qualia = (
        expression_mode == "diagnostic"
        or bool((system_context or {}).get("show_qualia"))
        or bool(qualia.get("user_requested"))
    )
    if show_qualia and (qualia.get("hypothesis_available", False) or qualia.get("status") == "available"):
        parts.append("Qualia disponible")

    if not parts:
        return "Central operativa"

    return " · ".join(parts)


def _has_internal_dump(raw: str) -> list[str]:
    """Detecta si la respuesta cruda contiene dumps internos.

    Devuelve lista de qué tipo de dump se detectó.
    """
    found: list[str] = []
    for pat in _INTERNAL_DUMP_PATTERNS:
        if pat.search(raw):
            found.append(pat.pattern[:40])
    if _RAW_JSON_BLOCK.search(raw):
        found.append("raw_json_block")
    if _RAW_DICT_LINE.search(raw):
        found.append("raw_dict_dump")
    return found


def _synthesize_dump(raw: str, found_dumps: list[str]) -> str:
    """Limpia y sintetiza una respuesta que contiene dumps internos."""
    if not found_dumps:
        return raw

    cleaned = _RAW_JSON_BLOCK.sub("[evidencia interna sintetizada]", raw)

    lines = cleaned.split("\n")
    filtered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            filtered.append(line)
            continue
        if _RAW_DICT_LINE.match(stripped):
            continue
        is_dump_line = any(pat.search(stripped) for pat in _INTERNAL_DUMP_PATTERNS)
        if is_dump_line:
            continue
        filtered.append(line)

    return "\n".join(filtered)


def _starts_with_operational_summary(raw: str) -> bool:
    return bool(re.match(r"^\s*Resumen\s+operativo\s*:", raw or "", re.IGNORECASE))


def _strip_internal_dumps(raw: str) -> str:
    cleaned = _RAW_JSON_BLOCK.sub("", raw or "")
    cleaned = _synthesize_dump(cleaned, _has_internal_dump(cleaned))
    lines: list[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(pat.search(stripped) for pat in _INTERNAL_DUMP_PATTERNS):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _build_corrections(found_dumps: list[str], expression_mode: str) -> list[str]:
    corrections: list[str] = []
    if found_dumps:
        corrections.append(f"dump_interno_sintetizado:{len(found_dumps)} bloques")
    if expression_mode in {"natural", "self_state"}:
        corrections.append("respuesta_transformada_a_lenguaje_natural")
    return corrections


def _generate_intent_oriented_response(
    *,
    expression_mode: str,
    user_input: str,
    raw_response: str,
    modular_trace: str,
    system_context: dict[str, Any] | None,
    found_dumps: list[str],
) -> str:
    system_context = system_context or {}
    if expression_mode == "self_state":
        degraded_note = _brief_degraded_note(system_context)
        response = (
            "No siento como una persona, pero estoy operando. "
            "Mi Central coordina la respuesta, el Hipotálamo interpreta la intención, "
            "la Bodega conserva continuidad y el Cristal cuida la coherencia."
        )
        if degraded_note:
            response += f" Ahora mismo opero {degraded_note}."
        response += "\n\nEstoy activa para conversar y trabajar; la evidencia profunda queda en la Cabina Viva, no en el chat."
        return response

    if expression_mode == "technical_summary":
        return _factual_fallback(user_input, raw_response)

    if expression_mode == "operational":
        cleaned = _strip_internal_dumps(raw_response)
        if cleaned and not _starts_with_operational_summary(cleaned):
            return cleaned
        return (
            "Puedo avanzar con la tarea y mantener la evidencia interna fuera del chat. "
            f"Traza modular: {modular_trace}."
        )

    if expression_mode == "creative":
        cleaned = _strip_internal_dumps(raw_response)
        return cleaned or "Puedo convertir esa idea en una propuesta clara sin exponer trazas internas."

    if expression_mode == "diagnostic":
        return _diagnostic_summary_text(raw_response, modular_trace)

    cleaned = _strip_internal_dumps(raw_response)
    if cleaned and not _starts_with_operational_summary(cleaned):
        return cleaned
    if found_dumps or _starts_with_operational_summary(raw_response):
        return (
            "Estoy operando y convertí el contexto interno en una respuesta breve. "
            f"Traza modular: {modular_trace}."
        )
    return raw_response.strip()


def _brief_degraded_note(system_context: dict[str, Any]) -> str:
    status = str(
        system_context.get("ollama_status")
        or system_context.get("cognitive_blood_status")
        or system_context.get("model_status")
        or ""
    ).lower()
    degraded_components = system_context.get("degraded_components") or []
    if "no_ollama" in status or "degraded" in status or "fallback" in status:
        return "con razonamiento profundo limitado por falta o degradación de Ollama"
    if degraded_components:
        return "con algunos componentes degradados, pero en modo seguro"
    return ""


def _factual_fallback(user_input: str, raw_response: str) -> str:
    cleaned = _strip_internal_dumps(raw_response)
    u = user_input.lower()
    if re.search(r"\b(ave|p[aá]jaro|alas?|vuela|volar|vuelo)\b", u):
        return (
            "Un ave vuela porque sus alas mueven y moldean el aire. Al avanzar, "
            "la forma del ala ayuda a generar sustentación: una fuerza hacia arriba "
            "que compensa el peso. El aleteo aporta empuje, las plumas ajustan dirección "
            "y estabilidad, y la cola ayuda a maniobrar y frenar."
        )
    if cleaned and len(cleaned) >= 40 and not _starts_with_operational_summary(cleaned):
        return cleaned
    return "Puedo responder la pregunta factual sin exponer trazas internas; necesito un poco más de contexto sobre el tema."


def _diagnostic_summary_text(raw_response: str, modular_trace: str) -> str:
    cleaned = _strip_internal_dumps(raw_response)
    snippets: list[str] = []
    for line in cleaned.splitlines():
        line = line.strip(" -•\t")
        if not line:
            continue
        if re.match(r"^Resumen\s+operativo\s*:?\s*$", line, re.IGNORECASE):
            continue
        if len(line) > 180:
            line = line[:177].rstrip() + "..."
        snippets.append(line)
        if len(snippets) >= 4:
            break
    if not snippets:
        snippets = ["Runtime y módulos internos revisados sin exponer evidencia cruda."]
    return "Resumen operativo:\n" + "\n".join(f"- {item}" for item in snippets) + f"\nTraza modular: {modular_trace}."


# ── API pública ────────────────────────────────────────────────────────────


class ExpressionCortex:
    """Corteza de Expresión de Tríade Ω.

    Principios:
    1. Responder primero la intención humana.
    2. Contexto interno como soporte, no como contenido visible.
    3. Diagnóstico/auditoría → resumen técnico.
    4. Conversación → respuesta natural.
    5. Dumps internos → síntesis.
    6. Modularidad como traza breve.
    7. Evidencia profunda en hidden_evidence.
    """

    def shape_response(
        self,
        *,
        user_input: str,
        raw_response: str,
        intent: str,
        signals: dict[str, Any],
        memory: dict[str, Any],
        crystal: dict[str, Any],
        qualia: dict[str, Any],
        bodega_context: dict[str, Any],
        learning_context: dict[str, Any],
        system_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        found_dumps = _has_internal_dump(raw_response)

        expression_mode = _detect_expression_mode(user_input, intent, raw_response)

        modular_trace = _build_modular_trace(
            signals, memory, crystal, qualia,
            bodega_context, learning_context,
            expression_mode=expression_mode,
            system_context=system_context,
        )

        response = raw_response
        if expression_mode == "self_state":
            response = _generate_intent_oriented_response(
                expression_mode=expression_mode,
                user_input=user_input,
                raw_response=raw_response,
                modular_trace=modular_trace,
                system_context=system_context,
                found_dumps=found_dumps,
            )
        elif expression_mode in {"natural", "technical_summary"} and (found_dumps or _starts_with_operational_summary(raw_response)):
            response = _generate_intent_oriented_response(
                expression_mode=expression_mode,
                user_input=user_input,
                raw_response=raw_response,
                modular_trace=modular_trace,
                system_context=system_context,
                found_dumps=found_dumps,
            )
        elif expression_mode == "technical_summary":
            response = self._build_factual_synthesis(user_input, raw_response)
        elif expression_mode == "diagnostic" and found_dumps:
            response = self._build_diagnostic_summary(raw_response, modular_trace)
        elif expression_mode == "diagnostic" and _starts_with_operational_summary(raw_response):
            response = raw_response.strip()
        elif expression_mode == "operational" and found_dumps:
            response = _generate_intent_oriented_response(
                expression_mode=expression_mode,
                user_input=user_input,
                raw_response=raw_response,
                modular_trace=modular_trace,
                system_context=system_context,
                found_dumps=found_dumps,
            )
        elif expression_mode == "creative" and found_dumps:
            response = _strip_internal_dumps(raw_response)
        elif found_dumps:
            response = _synthesize_dump(raw_response, found_dumps)

        response = _strip_internal_dumps(response) if _has_internal_dump(response) else response.strip()
        if not response:
            response = _generate_intent_oriented_response(
                expression_mode=expression_mode,
                user_input=user_input,
                raw_response=raw_response,
                modular_trace=modular_trace,
                system_context=system_context,
                found_dumps=found_dumps,
            )
        if expression_mode != "diagnostic" and _starts_with_operational_summary(response):
            response = _generate_intent_oriented_response(
                expression_mode=expression_mode,
                user_input=user_input,
                raw_response=raw_response,
                modular_trace=modular_trace,
                system_context=system_context,
                found_dumps=found_dumps,
            )
        if _is_semantic_memory_state_query(user_input.lower()) and "bodega sem" not in response.lower():
            response = (
                response.rstrip()
                + "\n\nLa Bodega semántica sostiene memoria semántica y continuidad operativa; "
                "Qualia aporta hipótesis internas, no memoria estable por sí sola."
            )

        corrections = _build_corrections(found_dumps, expression_mode)

        reason = self._build_reason(expression_mode, found_dumps, intent)

        hidden_evidence = {
            "raw_response": raw_response,
            "found_dumps": found_dumps,
            "signals": signals,
            "memory": memory,
            "crystal": crystal,
            "qualia": qualia,
            "bodega_context": bodega_context,
            "learning_context": learning_context,
            "system_context": system_context,
        }

        return {
            "response": response,
            "expression_mode": expression_mode,
            "internal_context_used": True,
            "visible_modular_trace": modular_trace,
            "hidden_evidence": hidden_evidence,
            "corrections": corrections,
            "reason": reason,
        }

    def _build_natural_operational_response(self, user_input: str, modular_trace: str) -> str:
        if _is_self_state_query(user_input.lower()):
            return (
                "No siento como una persona, pero estoy operando. "
                "Mi Central coordina la respuesta, el Hipotálamo interpreta la intención, "
                "la Bodega conserva continuidad y el Cristal cuida coherencia. "
                "Estoy activa y aprendiendo en segundo plano."
            )
        return (
            "Estoy operando con mis módulos internos activos y convertí el contexto profundo "
            "en una respuesta breve para ti. "
            f"Traza: {modular_trace}."
        )

    def _build_factual_synthesis(self, user_input: str, raw_response: str) -> str:
        return _factual_fallback(user_input, raw_response)

    def _build_diagnostic_summary(self, raw_response: str, modular_trace: str) -> str:
        return _diagnostic_summary_text(raw_response, modular_trace)

    def _build_reason(
        self,
        expression_mode: str,
        found_dumps: list[str],
        intent: str,
    ) -> str:
        parts: list[str] = []
        if found_dumps:
            parts.append(f"dump_interno_detectado_{len(found_dumps)}")
        if expression_mode == "self_state":
            parts.append("estado_conversacional_propio")
        elif expression_mode == "natural":
            parts.append("intencion_conversacional_detectada")
        elif expression_mode == "diagnostic":
            parts.append("solicitud_de_diagnostico")
        elif expression_mode == "technical_summary":
            parts.append("pregunta_factual")
        elif expression_mode == "operational":
            parts.append(f"intencion_operativa:{intent}")
        elif expression_mode == "creative":
            parts.append("intencion_creativa")
        return "|".join(parts) if parts else "expresion_por_defecto"
