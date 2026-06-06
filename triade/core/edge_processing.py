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


def summarize_with_edge(text: str) -> Dict[str, Any]:
    return EdgeProcessingService().summarize(text).to_dict()


def intent_probe_with_edge(text: str) -> Dict[str, Any]:
    return EdgeProcessingService().intent_probe(text).to_dict()


def keywords_with_edge(text: str) -> Dict[str, Any]:
    return EdgeProcessingService().keywords(text).to_dict()
