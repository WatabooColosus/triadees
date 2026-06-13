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


def parse_model_json_safely(text: str | None, *, fallback_text: str, parser_name: str) -> dict[str, Any]:
    """Convierte salida JSON de modelo en dato o señal; no lanza por JSON inválido."""
    raw = "" if text is None else str(text)
    stripped = raw.strip()
    base = {
        "parser_name": parser_name,
        "data": None,
        "raw_preview": " ".join(stripped.split())[:300],
        "empty": False,
        "non_json": False,
        "json_error": None,
        "fallback_required": True,
        "fallback_text_preview": " ".join(str(fallback_text or "").split())[:300],
    }
    if not stripped:
        return {
            **base,
            "ok": False,
            "empty": True,
            "signal_quality": "empty",
            "observation_type": "empty_response",
        }

    cleaned = stripped.replace("```json", "").replace("```", "").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    candidate = cleaned[start:end + 1] if start >= 0 and end > start else cleaned
    if "{" not in candidate or "}" not in candidate:
        return {
            **base,
            "ok": False,
            "non_json": True,
            "signal_quality": "low",
            "observation_type": "non_json_response",
        }

    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return {
            **base,
            "ok": False,
            "json_error": str(exc),
            "signal_quality": "low",
            "observation_type": "malformed_json",
        }
    if not isinstance(data, dict):
        return {
            **base,
            "ok": False,
            "non_json": True,
            "signal_quality": "low",
            "observation_type": "non_json_response",
        }
    return {
        **base,
        "ok": True,
        "data": data,
        "fallback_required": False,
        "signal_quality": "high",
        "observation_type": "valid_json",
    }


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
    edge_signal_quality: str
    edge_observations: list[dict[str, Any]]
    fallback_used: bool
    edge_confidence_score: float
    truth: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_edge_context(user_text: str, enable_summary: bool = False) -> Dict[str, Any]:
    started = time.time()
    service = EdgeProcessingService()

    evidence: Dict[str, Any] = {}
    edge_observations: list[dict[str, Any]] = []
    node_id: Optional[str] = None
    used_edge = False
    accepted = False

    probe_result = service.context_probe(user_text)
    evidence["context_probe"] = probe_result.to_dict()
    used_edge = used_edge or probe_result.used_edge
    accepted = accepted or probe_result.accepted_for_context
    node_id = probe_result.node_id or node_id

    probe = parse_context_probe(probe_result.response, fallback_text=user_text)
    edge_observations.extend(_extract_edge_observations(probe, "context_probe"))
    intent_data = probe["intent_probe"]
    keywords = probe["keywords"]

    # Fallback al flujo anterior solo si el probe único no fue aceptado.
    if not probe_result.accepted_for_context:
        intent_result = service.intent_probe(user_text)
        evidence["intent_probe"] = intent_result.to_dict()
        used_edge = used_edge or intent_result.used_edge
        accepted = accepted or intent_result.accepted_for_context
        node_id = intent_result.node_id or node_id
        intent_data = parse_intent(intent_result.response, fallback_text=user_text)
        edge_observations.extend(_extract_edge_observations(intent_data, "intent_probe"))

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

    intent_data = compact_intent_probe(intent_data)
    edge_signal_quality = _merge_signal_quality(edge_observations)
    fallback_used = any(bool(obs.get("fallback_used")) for obs in edge_observations)
    edge_confidence_score = _edge_confidence_score(
        observations=edge_observations,
        accepted_for_context=accepted,
        used_edge=used_edge,
    )

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
        edge_signal_quality=edge_signal_quality,
        edge_observations=edge_observations,
        fallback_used=fallback_used,
        edge_confidence_score=edge_confidence_score,
        truth=(
            "edge_context es auxiliar: Android procesa subtareas con sus propios recursos; "
            "la Central valida antes de usarlo."
        ),
    )
    return ctx.to_dict()






def compact_intent_probe(data: dict[str, Any]) -> dict[str, Any]:
    """Deja solo campos seguros para plan/memory_diff.

    El raw del modelo permanece en evidence; el contexto compacto no debe
    cargar respuestas truncadas o texto alucinado.
    """
    return {
        "intent": str(data.get("intent", "unknown")),
        "urgency": str(data.get("urgency", "medium")),
        "risk": str(data.get("risk", "low")),
        "needs_tool": bool(data.get("needs_tool", False)),
    }


def parse_context_probe(text: str, fallback_text: str = "") -> dict[str, Any]:
    """Parsea el probe único del edge.

    Devuelve un dict con intent_probe y keywords. Si el JSON viene incompleto
    o sucio, usa fallback determinista.
    """
    result = parse_model_json_safely(text, fallback_text=fallback_text, parser_name="context_probe")
    if not result["ok"]:
        _record_edge_signal(result, fallback_text=fallback_text, parser_name="context_probe")
        intent_data = heuristic_intent(fallback_text or text, raw=text)
        intent_data.update({
            "_edge_signal_quality": result["signal_quality"],
            "_edge_observation_type": result["observation_type"],
            "_fallback_used": True,
        })
        return {
            "ok": False,
            "intent_probe": intent_data,
            "keywords": heuristic_keywords(fallback_text or text),
            "fallback_reason": result["observation_type"],
            "edge_signal_quality": result["signal_quality"],
            "edge_observation_type": result["observation_type"],
            "fallback_used": True,
        }

    try:
        data = result["data"] or {}
        intent_data = {
            "intent": str(data.get("intent", "unknown")).strip().lower(),
            "urgency": normalize_level(data.get("urgency", "medium"), default="medium"),
            "risk": normalize_level(data.get("risk", "low"), default="low"),
            "needs_tool": normalize_bool_like(data.get("needs_tool", False)),
        }

        ft = (fallback_text or "").lower()
        if "apk" in ft and ("nodo" in ft or "procesamiento" in ft or "conectar" in ft):
            intent_data = {
                "intent": "connect_apk_node",
                "urgency": "medium",
                "risk": "low",
                "needs_tool": True,
            }

        raw_keywords = data.get("keywords", [])
        if isinstance(raw_keywords, str):
            keywords = parse_keywords(raw_keywords, fallback_text=fallback_text)
        elif isinstance(raw_keywords, list):
            keywords = [str(k).strip(" .;:-\t\n\"'") for k in raw_keywords if str(k).strip()]
            if not keywords or any(len(k) > 40 or "palabra clave" in k.lower() or "###" in k for k in keywords):
                keywords = heuristic_keywords(fallback_text)
            keywords = keywords[:8]
        else:
            keywords = heuristic_keywords(fallback_text)

        if not intent_data["intent"] or intent_data["intent"] == "unknown":
            intent_data = heuristic_intent(fallback_text or text, raw=text)

        return {
            "ok": True,
            "intent_probe": intent_data,
            "keywords": keywords,
            "edge_signal_quality": result["signal_quality"],
            "edge_observation_type": result["observation_type"],
            "fallback_used": False,
        }
    except Exception:
        malformed = {
            **result,
            "ok": False,
            "signal_quality": "low",
            "observation_type": "malformed_json",
        }
        _record_edge_signal(malformed, fallback_text=fallback_text, parser_name="context_probe")
        intent_data = heuristic_intent(fallback_text or text, raw=text)
        intent_data.update({
            "_edge_signal_quality": "low",
            "_edge_observation_type": "malformed_json",
            "_fallback_used": True,
        })
        return {
            "ok": False,
            "intent_probe": intent_data,
            "keywords": heuristic_keywords(fallback_text or text),
            "fallback_reason": "malformed_json",
            "edge_signal_quality": "low",
            "edge_observation_type": "malformed_json",
            "fallback_used": True,
        }



def parse_intent(text: str, fallback_text: str = "") -> Dict[str, Any]:
    result = parse_model_json_safely(text, fallback_text=fallback_text, parser_name="intent_probe")
    if result["ok"]:
        data = result["data"] or {}
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
                "_edge_signal_quality": result["signal_quality"],
                "_edge_observation_type": result["observation_type"],
                "_fallback_used": False,
            }
    else:
        _record_edge_signal(result, fallback_text=fallback_text, parser_name="intent_probe")

    # Fallback determinista desde el texto original, no desde la salida débil del LLM.
    intent_data = heuristic_intent(fallback_text or text, raw=text)
    intent_data.update({
        "_edge_signal_quality": result["signal_quality"],
        "_edge_observation_type": result["observation_type"],
        "_fallback_used": True,
    })
    return intent_data


def _record_edge_signal(result: dict[str, Any], *, fallback_text: str, parser_name: str) -> None:
    from triade.core.edge_observations import record_edge_observation

    record_edge_observation(
        parser_name=parser_name,
        observation_type=str(result.get("observation_type") or "unknown"),
        signal_quality=str(result.get("signal_quality") or "low"),
        fallback_used=True,
        raw_preview=str(result.get("raw_preview") or ""),
        user_text_preview=" ".join(str(fallback_text or "").split())[:300],
    )


def _extract_edge_observations(payload: dict[str, Any], parser_name: str) -> list[dict[str, Any]]:
    obs_type = payload.get("edge_observation_type") or payload.get("_edge_observation_type")
    quality = payload.get("edge_signal_quality") or payload.get("_edge_signal_quality")
    fallback = payload.get("fallback_used") if "fallback_used" in payload else payload.get("_fallback_used")
    nested = payload.get("intent_probe") if isinstance(payload.get("intent_probe"), dict) else {}
    obs_type = obs_type or nested.get("_edge_observation_type")
    quality = quality or nested.get("_edge_signal_quality")
    fallback = fallback if fallback is not None else nested.get("_fallback_used")
    if not obs_type:
        return []
    return [{
        "parser_name": parser_name,
        "observation_type": obs_type,
        "signal_quality": quality or "low",
        "fallback_used": bool(fallback),
    }]


def _merge_signal_quality(observations: list[dict[str, Any]]) -> str:
    if not observations:
        return "high"
    qualities = {str(obs.get("signal_quality") or "low") for obs in observations}
    types = {str(obs.get("observation_type") or "") for obs in observations}
    if "empty_response" in types or "empty" in qualities:
        return "empty"
    if "low" in qualities:
        return "low"
    if "medium" in qualities:
        return "medium"
    return "high"


def _edge_confidence_score(*, observations: list[dict[str, Any]], accepted_for_context: bool, used_edge: bool) -> float:
    types = {str(obs.get("observation_type") or "") for obs in observations}
    score = 0.0
    if not observations or "valid_json" in types:
        score += 0.5
    if accepted_for_context:
        score += 0.3
    if used_edge:
        score += 0.2
    cap = 1.0
    if "empty_response" in types:
        cap = 0.2
    elif types & {"non_json_response", "malformed_json"}:
        cap = 0.3
    return round(min(score, cap), 3)


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
