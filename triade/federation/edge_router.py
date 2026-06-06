"""
Edge Router para Tríade Ω.

Este módulo trata nodos Android/edge como capacidad distribuida por tarea.
No suma RAM del Android a la PC. No implementa memory pooling ni tensor parallel.
La federación actual es task-parallel: el 8010 envía jobs completos al nodo edge,
el nodo ejecuta con sus propios recursos, y devuelve resultado auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple
import json
import time
import urllib.error
import urllib.request


LIGHTWEIGHT_TASKS = {
    "preprocess_text",
    "intent_probe",
    "short_summary",
    "keyword_extract",
    "style_rewrite",
    "local_reflection",
    "android_local_generate",
}


@dataclass
class EdgeNodeLease:
    node_id: str
    name: str
    online: bool
    transport: str
    can_host_llm: bool
    lease_status: str
    edge_cpu_threads_available: int
    edge_ram_available_gb: float
    model_runtime_backend: str
    allowed_tasks: list[str]
    raw: Dict[str, Any]

    @property
    def is_ready(self) -> bool:
        return bool(
            self.online
            and self.can_host_llm
            and self.lease_status == "llm_host_ready"
            and self.edge_cpu_threads_available >= 1
        )


class EdgeRouter:
    """
    Router de capacidad edge.

    Responsabilidad:
    - Consultar /api/federation/resource-lease.
    - Seleccionar nodos edge aptos.
    - Enviar subtareas ligeras al Android LLM runtime.
    - Devolver resultado + evidencia.

    No debe:
    - Modificar memoria estable.
    - Sustituir a la Central.
    - Sumar RAM edge como RAM de PC/Ollama.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8010", timeout_seconds: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_resource_lease(self) -> Dict[str, Any]:
        return self._request_json("GET", "/api/federation/resource-lease?sync_relay=true")

    def list_edge_llm_nodes(self) -> list[EdgeNodeLease]:
        data = self.get_resource_lease()
        leases = data.get("leases", []) or []
        nodes: list[EdgeNodeLease] = []
        for item in leases:
            nodes.append(
                EdgeNodeLease(
                    node_id=str(item.get("node_id", "")),
                    name=str(item.get("name", "")),
                    online=bool(item.get("online", False)),
                    transport=str(item.get("transport", "")),
                    can_host_llm=bool(item.get("can_host_llm", False)),
                    lease_status=str(item.get("lease_status", "")),
                    edge_cpu_threads_available=int(item.get("cpu_authorized_count") or 0),
                    edge_ram_available_gb=float(item.get("ram_available_gb") or item.get("ram_authorized_gb") or 0.0),
                    model_runtime_backend=str(item.get("model_runtime_backend", "")),
                    allowed_tasks=list(item.get("allowed_tasks", []) or []),
                    raw=item,
                )
            )
        return nodes

    def select_node(self, task: str = "android_local_generate") -> Optional[EdgeNodeLease]:
        for node in self.list_edge_llm_nodes():
            if not node.is_ready:
                continue
            if task in node.allowed_tasks or "android_local_generate" in node.allowed_tasks:
                return node
        return None

    def should_route_to_edge(self, task: str, text: str, max_chars: int = 2500) -> Tuple[bool, str]:
        if task not in LIGHTWEIGHT_TASKS:
            return False, "task_not_lightweight"
        if not text or not text.strip():
            return False, "empty_text"
        if len(text) > max_chars:
            return False, "text_too_large_for_edge"
        node = self.select_node("android_local_generate")
        if not node:
            return False, "no_ready_edge_llm_node"
        return True, "ready"

    def generate_on_android(
        self,
        prompt: str,
        max_tokens: int = 80,
        context_tokens: int = 2048,
        wait_timeout: int = 120,
    ) -> Dict[str, Any]:
        started = time.time()
        payload = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "context_tokens": context_tokens,
            "wait_timeout": wait_timeout,
        }
        result = self._request_json(
            "POST",
            "/api/distributed-runtime/android-local-generate",
            payload=payload,
            timeout=wait_timeout + 10,
        )
        result["_edge_router"] = {
            "routed": True,
            "task_parallel": True,
            "memory_pooling": False,
            "tensor_parallel": False,
            "elapsed_router_ms": int((time.time() - started) * 1000),
            "truth": "Android ejecuta la inferencia con sus propios recursos; 8010 solo orquesta y audita.",
        }
        return result

    def run_lightweight_task(self, task: str, text: str, instruction: Optional[str] = None) -> Dict[str, Any]:
        should_route, reason = self.should_route_to_edge(task, text)
        if not should_route:
            return {
                "status": "skipped",
                "task": task,
                "reason": reason,
                "edge_result": None,
                "truth": "No se usó Android edge; debe caer a PC/Ollama o flujo local.",
            }

        if instruction is None:
            instruction = self._default_instruction(task)

        prompt = (
            "### Instruction:\n"
            f"{instruction}\n\n"
            "### Input:\n"
            f"{text.strip()}\n\n"
            "### Response:\n"
        )

        return self.generate_on_android(prompt=prompt, max_tokens=96, context_tokens=2048)

    def semantic_summary(self) -> Dict[str, Any]:
        node = self.select_node("android_local_generate")
        return {
            "mode": "task_parallel_edge_federation",
            "memory_pooling": False,
            "tensor_parallel": False,
            "pc_role": ["orchestrator", "router", "central", "bodega", "audit", "fallback"],
            "edge_role": ["local_inference", "lightweight_tasks", "preprocessing", "short_generation"],
            "selected_node": asdict(node) if node else None,
            "truth": "La RAM del Android no se suma a la RAM de la PC; Android aporta capacidad de procesamiento por tarea.",
        }

    def _default_instruction(self, task: str) -> str:
        if task == "intent_probe":
            return "Analiza la intención del texto y responde en JSON corto con intent, urgency y risk."
        if task == "short_summary":
            return "Resume el texto en español en una frase corta."
        if task == "keyword_extract":
            return "Extrae máximo 8 palabras clave en español separadas por coma."
        if task == "style_rewrite":
            return "Reescribe el texto en español claro y breve."
        if task == "local_reflection":
            return "Da una reflexión breve y útil en español."
        return "Responde en español de forma breve y directa."

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            return {
                "status": "error",
                "error": f"HTTP {exc.code}",
                "body": body,
                "url": url,
            }
        except Exception as exc:
            return {
                "status": "error",
                "error": str(exc),
                "url": url,
            }


def edge_semantics() -> Dict[str, Any]:
    return EdgeRouter().semantic_summary()


def edge_generate(prompt: str, max_tokens: int = 80) -> Dict[str, Any]:
    return EdgeRouter().generate_on_android(prompt=prompt, max_tokens=max_tokens)


if __name__ == "__main__":
    router = EdgeRouter()
    print(json.dumps(router.semantic_summary(), ensure_ascii=False, indent=2))
