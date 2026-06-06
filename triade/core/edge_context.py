"""
Construcción de edge_context para runs de Tríade Ω.

El edge_context es una capa auxiliar para la Central:
- resume señales edge,
- no modifica memoria estable,
- no decide por la Central,
- conserva evidencia de nodo usado.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
import json
import time

from triade.core.edge_processing import EdgeProcessingService


@dataclass
class EdgeContext:
    enabled: bool
    used_edge: bool
    accepted: bool
    node_id: Optional[str]
    elapsed_ms: int
    intent_probe: Dict[str, Any]
    keywords: list[str]
    summary: str
    evidence: Dict[str, Any]
    truth: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_edge_context(user_text: str, enable_summary: bool = False) -> Dict[str, Any]:
    started = time.time()
    service = EdgeProcessingService()

    evidence: Dict[str, Any] = {}
    node_id: Optional[str] = None
    used_edge = False
    accepted = False

    intent_result = service.intent_probe(user_text)
    evidence["intent_probe"] = intent_result.to_dict()
    used_edge = used_edge or intent_result.used_edge
    accepted = accepted or intent_result.accepted_for_context
    node_id = intent_result.node_id or node_id

    intent_data = parse_intent(intent_result.response)

    keywords_result = service.keywords(user_text)
    evidence["keywords"] = keywords_result.to_dict()
    used_edge = used_edge or keywords_result.used_edge
    accepted = accepted or keywords_result.accepted_for_context
    node_id = keywords_result.node_id or node_id

    keywords = parse_keywords(keywords_result.response, fallback_text=user_text)

    summary = ""
    if enable_summary or len(user_text) > 280:
        summary_result = service.summarize(user_text)
        evidence["summary"] = summary_result.to_dict()
        used_edge = used_edge or summary_result.used_edge
        accepted = accepted or summary_result.accepted_for_context
        node_id = summary_result.node_id or node_id
        summary = summary_result.response

    ctx = EdgeContext(
        enabled=True,
        used_edge=used_edge,
        accepted=accepted,
        node_id=node_id,
        elapsed_ms=int((time.time() - started) * 1000),
        intent_probe=intent_data,
        keywords=keywords,
        summary=summary,
        evidence=evidence,
        truth=(
            "edge_context es auxiliar: Android procesa subtareas con sus propios recursos; "
            "la Central valida antes de usarlo."
        ),
    )
    return ctx.to_dict()


def parse_intent(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
        return {
            "intent": str(data.get("intent", "unknown")),
            "urgency": str(data.get("urgency", "medium")),
            "risk": str(data.get("risk", "low")),
            "needs_tool": bool(data.get("needs_tool", False)),
        }
    except Exception:
        return {
            "intent": "unknown",
            "urgency": "medium",
            "risk": "low",
            "needs_tool": False,
            "raw": text,
        }


def parse_keywords(text: str, fallback_text: str = "") -> list[str]:
    raw = (text or "").replace("\n", ",")
    parts = []
    for item in raw.split(","):
        clean = item.strip(" .;:-\t\n\"'")
        if clean:
            parts.append(clean)

    # Si el modelo devolvió una frase entera en vez de lista, usar extracción simple del input.
    if len(parts) <= 2 and fallback_text:
        parts = heuristic_keywords(fallback_text)

    result = []
    seen = set()
    for part in parts:
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        if len(part) > 40:
            continue
        result.append(part)
        if len(result) >= 8:
            break
    return result


def heuristic_keywords(text: str) -> list[str]:
    stop = {
        "es", "una", "un", "de", "del", "la", "el", "los", "las", "con", "y",
        "por", "para", "en", "como", "que", "se", "a", "al"
    }
    words = []
    for token in text.replace(".", " ").replace(",", " ").split():
        clean = token.strip(" .;:-\t\n\"'").lower()
        if len(clean) < 4:
            continue
        if clean in stop:
            continue
        if clean not in words:
            words.append(clean)
        if len(words) >= 8:
            break
    return words
