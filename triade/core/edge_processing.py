"""
Capa de procesamiento edge para Tríade Ω.

Conecta la Central/Hipotálamo con nodos Android federados sin exponer detalles
del transporte. Esta capa mantiene una regla crítica:

- Android aporta inferencia local por tarea.
- Android NO aporta RAM compartida a la PC.
- Android NO modifica memoria estable.
- La Central siempre valida el resultado antes de usarlo.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
import time
import re
import json

from triade.federation.edge_router import EdgeRouter


@dataclass
class EdgeProcessingResult:
    used_edge: bool
    accepted_for_context: bool
    task: str
    text: str
    node_id: Optional[str]
    elapsed_ms: int
    reason: str
    response: str
    raw: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EdgeProcessingService:
    """
    Servicio estable para tareas ligeras en nodos edge.

    La Central puede usar:
    - summarize()
    - intent_probe()
    - keywords()
    - rewrite()

    Cada resultado debe ser tratado como sugerencia, no como verdad final.
    """

    def __init__(self, router: Optional[EdgeRouter] = None):
        self.router = router or EdgeRouter()

    def summarize(self, text: str) -> EdgeProcessingResult:
        return self._run(
            task="short_summary",
            text=text,
            instruction=(
                "Resume el texto en español en una sola frase. "
                "No agregues introducciones como 'El texto anterior'. "
                "Devuelve solo el resumen final."
            ),
        )

    def intent_probe(self, text: str) -> EdgeProcessingResult:
        return self._run(
            task="intent_probe",
            text=text,
            instruction=(
                "Analiza la intención del usuario. Responde en JSON compacto con: "
                "intent, urgency, risk, needs_tool. No agregues explicación."
            ),
        )

    def keywords(self, text: str) -> EdgeProcessingResult:
        return self._run(
            task="keyword_extract",
            text=text,
            instruction=(
                "Extrae máximo 8 palabras clave en español, separadas por coma. "
                "Devuelve solo la lista."
            ),
        )

    def rewrite(self, text: str) -> EdgeProcessingResult:
        return self._run(
            task="style_rewrite",
            text=text,
            instruction=(
                "Reescribe el texto en español claro, breve y operativo. "
                "Devuelve solo la versión reescrita."
            ),
        )

    def _run(self, task: str, text: str, instruction: str) -> EdgeProcessingResult:
        started = time.time()
        should_route, reason = self.router.should_route_to_edge(task, text)
        if not should_route:
            return EdgeProcessingResult(
                used_edge=False,
                accepted_for_context=False,
                task=task,
                text=text,
                node_id=None,
                elapsed_ms=int((time.time() - started) * 1000),
                reason=reason,
                response="",
                raw={"status": "skipped", "reason": reason},
            )

        raw = self.router.run_lightweight_task(task=task, text=text, instruction=instruction)
        response = extract_response(raw)
        response = normalize_task_response(task, response)
        node_id = raw.get("node_id") or raw.get("job", {}).get("node_id")
        ok = bool(raw.get("status") == "ok" and response)

        return EdgeProcessingResult(
            used_edge=True,
            accepted_for_context=ok,
            task=task,
            text=text,
            node_id=node_id,
            elapsed_ms=int((time.time() - started) * 1000),
            reason="ok" if ok else "edge_returned_empty_or_failed",
            response=response,
            raw=raw,
        )


def extract_response(raw: Dict[str, Any]) -> str:
    """
    Extrae respuesta limpia desde diferentes formas de payload.
    """
    if not isinstance(raw, dict):
        return ""

    direct = raw.get("response")
    if isinstance(direct, str) and direct.strip():
        return normalize_edge_text(direct)

    result = raw.get("result")
    if isinstance(result, dict):
        for key in ("generated_text", "response"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return normalize_edge_text(value)

    job = raw.get("job")
    if isinstance(job, dict):
        job_result = job.get("result")
        if isinstance(job_result, dict):
            for key in ("generated_text", "response"):
                value = job_result.get(key)
                if isinstance(value, str) and value.strip():
                    return normalize_edge_text(value)

    return ""


def normalize_edge_text(text: str) -> str:
    out = text.strip()
    prefixes = [
        "El texto anterior fue resumido en español como:",
        "El texto anterior fue resumido como:",
        "Resumen:",
        "Respuesta:",
        "Fraza corta:",
        "Frase corta:",
    ]
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if out.lower().startswith(prefix.lower()):
                out = out[len(prefix):].strip()
                changed = True

    out = out.replace("[end of text]", "").replace("</s>", "").replace("<s>", "").strip()

    if len(out) >= 2 and out[0] == '"' and out[-1] == '"':
        out = out[1:-1].strip()

    return out


def normalize_task_response(task: str, response: str) -> str:
    """
    Normalización específica por tarea edge.
    El nodo Android/TinyLlama es sugerente, no autoridad final.
    Esta función limpia encabezados, continuaciones y formatos débiles.
    """
    out = normalize_edge_text(response)
    if not out:
        return ""

    if task == "intent_probe":
        return normalize_intent_probe(out)

    if task == "keyword_extract":
        return normalize_keywords(out)

    if task == "short_summary":
        return normalize_summary(out)

    return out


def normalize_summary(text: str) -> str:
    out = normalize_edge_text(text)
    out = re.sub(r'(?i)^el texto anterior fue resumido en español como:\s*', '', out).strip()
    out = re.sub(r'(?i)^el texto anterior fue resumido como:\s*', '', out).strip()
    out = re.sub(r'(?i)^resumen:\s*', '', out).strip()
    if len(out) >= 2 and out[0] == '"' and out[-1] == '"':
        out = out[1:-1].strip()
    return out


def normalize_keywords(text: str) -> str:
    out = normalize_edge_text(text)
    out = re.sub(r'(?i)^máximo\s+\d+\s+palabras\s+clave:\s*', '', out).strip()
    out = re.sub(r'(?i)^palabras\s+clave:\s*', '', out).strip()

    # Convertir listas numeradas o por líneas en partes separadas.
    out = re.sub(r'(?m)^\s*\d+\.\s*', '', out)
    out = out.replace("\n", ", ")

    raw_parts = []
    for chunk in out.split(","):
        chunk = chunk.strip(" .;:\t\n")
        if not chunk:
            continue
        # Si aún quedan piezas tipo "1. Tríade 2. Modular", separarlas.
        subparts = re.split(r'\s+\d+\.\s+', chunk)
        raw_parts.extend([s.strip(" .;:\t\n") for s in subparts if s.strip()])

    clean = []
    seen = set()
    stopwords = {"a", "de", "con", "y", "el", "la", "los", "las", "un", "una", "por", "run"}
    for part in raw_parts:
        part = re.sub(r'^\d+\.\s*', '', part).strip()
        if not part:
            continue
        if part.lower() in stopwords:
            continue
        key = part.lower()
        if key in seen:
            continue
        seen.add(key)
        clean.append(part)
        if len(clean) >= 8:
            break

    return ", ".join(clean)


def normalize_intent_probe(text: str) -> str:
    out = normalize_edge_text(text)
    out = out.replace("```json", "").replace("```", "").strip()

    # Cortar cualquier continuación tipo ejemplo o input posterior.
    cut_markers = ["### Example", "### Ejemplo", "### Input:", "\nExample", "\nEjemplo"]
    for marker in cut_markers:
        idx = out.find(marker)
        if idx >= 0:
            out = out[:idx].strip()

    candidate = first_json_object(out)
    if candidate:
        try:
            data = json.loads(candidate)
            normalized = {
                "intent": normalize_enum_text(data.get("intent", "unknown")),
                "urgency": normalize_level(data.get("urgency", "medium"), default="medium"),
                "risk": normalize_level(data.get("risk", "low"), default="low"),
                "needs_tool": normalize_bool_like(data.get("needs_tool", False)),
            }
            return json.dumps(normalized, ensure_ascii=False)
        except Exception:
            return candidate

    return out.strip()


def first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1].strip()
    return ""


def normalize_enum_text(value) -> str:
    return str(value).strip().lower().replace("need_", "").replace("connect_appkg", "connect_apk")


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
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "yes", "si", "sí", "1", "y"}:
            return True
        if v in {"false", "no", "0", "none", "null"}:
            return False
        # Si el modelo respondió con nombres de herramientas en vez de bool,
        # interpretamos que sí requiere herramienta.
        return bool(v)
    return False


def summarize_with_edge(text: str) -> Dict[str, Any]:
    return EdgeProcessingService().summarize(text).to_dict()


def intent_probe_with_edge(text: str) -> Dict[str, Any]:
    return EdgeProcessingService().intent_probe(text).to_dict()


def keywords_with_edge(text: str) -> Dict[str, Any]:
    return EdgeProcessingService().keywords(text).to_dict()
