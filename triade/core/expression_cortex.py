"""Corteza de Expresión — Tríade Ω.

Transforma la respuesta cruda del modelo en una síntesis humana adecuada al
contexto conversacional, preservando la evidencia profunda para Cabina Viva.
"""

from __future__ import annotations

import re
from typing import Any

# ── Marcadores internos que la Corteza debe detectar y sintetizar ──────────

_INTERNAL_DUMP_PATTERNS: list[re.Pattern] = [
    re.compile(r"bodega[_\s]global|bodega[_\s]summary|global[_\s]context", re.IGNORECASE),
    re.compile(r"qualia[_\s]bus|qualia[_\s]signals|qualia[_\s]experiences", re.IGNORECASE),
    re.compile(r"memory[_\s]trace|memory[_\s]diff|semantic[_\s]recall", re.IGNORECASE),
    re.compile(r"neuron[_\s]candidate|neuron[_\s]proposal|candidate[_\s]gate", re.IGNORECASE),
    re.compile(r"learning[_\s]journal|post[_\s]run[_\s]learning|learning[_\s]candidate", re.IGNORECASE),
    re.compile(r"readiness.*:.*\d|readiness[_\s]report", re.IGNORECASE),
    re.compile(r"system_events\s*:?\s*\[", re.IGNORECASE),
    re.compile(r"background[_\s]neuron[_\s]candidates", re.IGNORECASE),
    re.compile(r"experimental[_\s]neuron[_\s]activity", re.IGNORECASE),
    re.compile(r"run_path|run_id.*:.*[a-f0-9]{8}", re.IGNORECASE),
    re.compile(r"output[_\s]gate|coherence.*trace|deduplication.*trace", re.IGNORECASE),
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

    # Diagnóstico / auditoría / estado
    if any(w in u for w in ("audita", "diagnóstico", "verifica", "status",
                             "health", "revisa", "que pasó", "que paso", "reporte",
                             "auditar", "revisión", "diagnóstico", "audit", "check")):
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


def _build_modular_trace(
    signals: dict[str, Any],
    memory: dict[str, Any],
    crystal: dict[str, Any],
    qualia: dict[str, Any],
    bodega_context: dict[str, Any],
    learning_context: dict[str, Any],
) -> str:
    """Construye una traza breve de los módulos internos usados.

    Ejemplo: "Central enfocada · Hipotálamo estable · Bodega disponible ·
    Cristal coherente · Aprendizaje activo"
    """
    parts: list[str] = []

    hypothalamus_ok = signals.get("hypothalamus_quality", 0) > 0.3
    parts.append("Hipotálamo estable" if hypothalamus_ok else "Hipotálamo")

    bodega_ok = bool(bodega_context.get("domain_count", 0) > 0)
    parts.append("Bodega disponible" if bodega_ok else "Bodega")

    crystal_status = crystal.get("temporal_status", crystal.get("status", "unknown"))
    if crystal_status in ("coherent", "available"):
        parts.append("Cristal coherente")
    else:
        parts.append(f"Cristal {crystal_status}")

    if memory.get("semantic_matches", 0) > 0 or memory.get("confidence", 0) > 0.3:
        parts.append("Memoria presente")

    if learning_context.get("active", False) or learning_context.get("enabled", False):
        parts.append("Aprendizaje activo")

    if qualia.get("hypothesis_available", False) or qualia.get("status") == "available":
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
        if len(stripped) > 300 and any(c in stripped for c in ("bodega", "qualia", "candidate", "neuron")):
            filtered.append(stripped[:120] + "... [datos internos truncados]")
            continue
        filtered.append(line)

    return "\n".join(filtered)


def _build_corrections(found_dumps: list[str], expression_mode: str) -> list[str]:
    corrections: list[str] = []
    if found_dumps:
        corrections.append(f"dump_interno_sintetizado:{len(found_dumps)} bloques")
    if expression_mode == "natural":
        corrections.append("respuesta_transformada_a_lenguaje_natural")
    return corrections


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

        response = raw_response
        if found_dumps:
            response = _synthesize_dump(raw_response, found_dumps)

        corrections = _build_corrections(found_dumps, expression_mode)

        modular_trace = _build_modular_trace(
            signals, memory, crystal, qualia,
            bodega_context, learning_context,
        )

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

    def _build_reason(
        self,
        expression_mode: str,
        found_dumps: list[str],
        intent: str,
    ) -> str:
        parts: list[str] = []
        if found_dumps:
            parts.append(f"dump_interno_detectado_{len(found_dumps)}")
        if expression_mode == "natural":
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
