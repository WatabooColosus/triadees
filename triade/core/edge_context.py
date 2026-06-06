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

    intent_data = parse_intent(intent_result.response, fallback_text=user_text)

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
        summary = sanitize_summary(summary_result.response, fallback_text=user_text)

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


def parse_intent(text: str, fallback_text: str = "") -> Dict[str, Any]:
    try:
        data = json.loads(text)
        intent = str(data.get("intent", "unknown")).strip().lower()
        urgency = normalize_level(data.get("urgency", "medium"), default="medium")
        risk = normalize_level(data.get("risk", "low"), default="low")
        needs_tool = normalize_bool_like(data.get("needs_tool", False))
        if intent and intent != "unknown":
            # Corrección determinista para tareas técnicas APK/nodo.
            ft = (fallback_text or "").lower()
            if "apk" in ft and ("nodo" in ft or "procesamiento" in ft or "conectar" in ft):
                intent = "connect_apk_node"
                urgency = "medium"
                risk = "low"
                needs_tool = True

            return {
                "intent": intent,
                "urgency": urgency,
                "risk": risk,
                "needs_tool": needs_tool,
            }
    except Exception:
        pass

    # Fallback determinista desde el texto original, no desde la salida débil del LLM.
    return heuristic_intent(fallback_text or text, raw=text)


def parse_keywords(text: str, fallback_text: str = "") -> list[str]:
    raw = (text or "").replace("\n", ",")
    parts = []
    for item in raw.split(","):
        clean = item.strip(" .;:-\t\n\"'")
        if clean:
            parts.append(clean)

    # Si el modelo devolvió explicación, frase larga o poca separación, usar input original.
    too_long = any(len(p) > 42 for p in parts)
    looks_like_explanation = any(
        p.lower().startswith((
            "el proceso",
            "por ejemplo",
            "para ",
            "debemos",
            "a continuación",
            "más de",
            "mas de",
            "las cuales son",
            "se han encontrado",
        ))
        for p in parts
    )
    weak_keywords = any(
        "palabras clave" in p.lower()
        or "palabra clave" in p.lower()
        or "```" in p
        or "###" in p
        or p.lower().startswith("el nombre")
        or p.lower().startswith("la palabra")
        or '"' in p
        or " en español" in p.lower()
        for p in parts
    )
    if fallback_text and (len(parts) <= 2 or too_long or looks_like_explanation or weak_keywords):
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


def sanitize_summary(text: str, fallback_text: str = "") -> str:
    out = (text or "").strip()
    lower = out.lower()
    if (
        "### input" in lower
        or "### response" in lower
        or "google play" in lower
        or len(out) > 260
    ):
        return heuristic_summary(fallback_text)
    return out


def heuristic_summary(text: str) -> str:
    clean = " ".join((text or "").strip().split())
    if not clean:
        return ""
    if len(clean) <= 180:
        return clean
    return clean[:177].rstrip() + "..."


def heuristic_intent(text: str, raw: str = "") -> Dict[str, Any]:
    t = (text or "").lower()
    intent = "general"
    needs_tool = False

    if "apk" in t and ("conectar" in t or "nodo" in t or "procesamiento" in t):
        intent = "conectar_apk_nodo"
        needs_tool = True
    elif "git" in t or "github" in t or "push" in t:
        intent = "git_devops"
        needs_tool = True
    elif "error" in t or "fall" in t or "traceback" in t:
        intent = "debug"
        needs_tool = True

    urgency = "medium"
    if any(w in t for w in ("urgente", "ya", "ahora", "crítico", "critico")):
        urgency = "high"

    risk = "low"
    if any(w in t for w in ("token", "contraseña", "password", "permiso", "credencial")):
        risk = "medium"

    data = {
        "intent": intent,
        "urgency": urgency,
        "risk": risk,
        "needs_tool": needs_tool,
    }
    if raw:
        data["raw_edge"] = raw
    return data


def normalize_level(value, default: str = "medium") -> str:
    if isinstance(value, (int, float)):
        if value <= 1:
            return "low"
        if value == 2:
            return "medium"
        return "high"
    v = str(value).strip().lower()
    mapping = {
        "1": "low",
        "2": "medium",
        "3": "high",
        "normal": "medium",
        "baja": "low",
        "media": "medium",
        "alta": "high",
        "low": "low",
        "medium": "medium",
        "high": "high",
    }
    return mapping.get(v, default)


def normalize_bool_like(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    v = str(value).strip().lower()
    if v in {"true", "yes", "si", "sí", "1", "y"}:
        return True
    if v in {"false", "no", "0", "none", "null"}:
        return False
    return bool(v)
