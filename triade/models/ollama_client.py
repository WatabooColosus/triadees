"""Ollama adapter with safe fallback for Tríade."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from triade.models.model_router import ModelRouter


@dataclass(slots=True)
class ModelResult:
    ok: bool
    text: str
    model: str
    provider: str = "ollama"
    error: str | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "model": self.model,
            "provider": self.provider,
            "error": self.error,
            "total_duration": self.total_duration,
            "load_duration": self.load_duration,
            "prompt_eval_count": self.prompt_eval_count,
            "eval_count": self.eval_count,
        }


@dataclass(slots=True)
class EmbeddingResult:
    """Resultado trazable de una petición de embeddings a Ollama."""

    ok: bool
    model: str
    embeddings: list[list[float]] = field(default_factory=list)
    provider: str = "ollama"
    error: str | None = None
    total_duration: int | None = None
    load_duration: int | None = None
    prompt_eval_count: int | None = None

    @property
    def dimensions(self) -> int:
        return len(self.embeddings[0]) if self.embeddings else 0

    def to_dict(self, include_vectors: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "model": self.model,
            "provider": self.provider,
            "error": self.error,
            "count": len(self.embeddings),
            "dimensions": self.dimensions,
            "total_duration": self.total_duration,
            "load_duration": self.load_duration,
            "prompt_eval_count": self.prompt_eval_count,
        }
        if include_vectors:
            payload["embeddings"] = self.embeddings
        return payload


class OllamaClient:
    """Minimal HTTP client for local Ollama.

    Uses the local Ollama REST API. If Ollama is unavailable, the caller can
    keep using template fallback without failing the run.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: int = 60,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.event_callback = event_callback

    def _observe(self, payload: dict[str, Any]) -> None:
        """Notifica metadatos seguros; observar nunca puede romper la inferencia."""
        if self.event_callback is None:
            return
        try:
            self.event_callback(payload)
        except Exception:  # noqa: BLE001  # callback de observabilidad aislado
            return

    def _device_report(self, model: str) -> dict[str, Any]:
        """Lee /api/ps después de trabajo real; no carga ni mantiene modelos."""
        if self.event_callback is None:
            return {"device_reported": "unknown", "size_vram": None}
        request = urllib.request.Request(f"{self.base_url}/api/ps", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            for loaded in parsed.get("models", []):
                if str(loaded.get("name") or loaded.get("model") or "") == model:
                    size_vram = int(loaded.get("size_vram") or 0)
                    return {
                        "device_reported": "gpu" if size_vram > 0 else "cpu",
                        "size_vram": size_vram,
                    }
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            AttributeError,
            TypeError,
            ValueError,
        ):
            pass
        return {"device_reported": "unknown", "size_vram": None}

    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> ModelResult:
        """Genera texto. `options` viaja tal cual al campo `options` de Ollama.

        Sirve para fijar `temperature`, `seed` o `top_p` cuando una evaluación
        necesita ser reproducible. Sin `options` el comportamiento no cambia:
        se omite el campo y Ollama aplica sus propios valores por defecto, que
        es lo que hacían todas las llamadas existentes.
        """
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if options:
            payload["options"] = dict(options)

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
                result = ModelResult(
                    ok=True,
                    text=str(parsed.get("response", "")).strip(),
                    model=str(parsed.get("model") or model),
                    total_duration=parsed.get("total_duration"),
                    load_duration=parsed.get("load_duration"),
                    prompt_eval_count=parsed.get("prompt_eval_count"),
                    eval_count=parsed.get("eval_count"),
                )
                self._observe(
                    {
                        "operation": "generate",
                        "endpoint": f"{self.base_url}/api/generate",
                        "requested_model": model,
                        "model_used": result.model,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        "total_duration": result.total_duration,
                        "load_duration": result.load_duration,
                        "prompt_eval_count": result.prompt_eval_count,
                        "eval_count": result.eval_count,
                        "ok": True,
                        **self._device_report(result.model),
                    }
                )
                return result
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            ImportError,
        ) as exc:
            result = ModelResult(
                ok=False,
                text="",
                model=model,
                error=str(exc),
            )
            self._observe(
                {
                    "operation": "generate",
                    "endpoint": f"{self.base_url}/api/generate",
                    "requested_model": model,
                    "model_used": model,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "ok": False,
                    "error": str(exc),
                }
            )
            return result

    def embed(
        self,
        model: str,
        input_text: str | list[str],
        truncate: bool = True,
        dimensions: int | None = None,
    ) -> EmbeddingResult:
        """Genera embeddings mediante el endpoint local POST /api/embed."""
        if not model.strip():
            return EmbeddingResult(
                ok=False,
                model=model,
                error="Debe especificarse el modelo de embedding.",
            )
        if isinstance(input_text, str):
            if not input_text.strip():
                return EmbeddingResult(
                    ok=False,
                    model=model,
                    error="El texto para embedding no puede estar vacío.",
                )
        elif not input_text or not all(str(item).strip() for item in input_text):
            return EmbeddingResult(
                ok=False,
                model=model,
                error="Los textos para embedding no pueden estar vacíos.",
            )

        payload: dict[str, Any] = {
            "model": model.strip(),
            "input": input_text,
            "truncate": truncate,
        }
        if dimensions is not None:
            payload["dimensions"] = dimensions
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                vectors = parsed.get("embeddings", [])
                if (
                    not isinstance(vectors, list)
                    or not vectors
                    or not all(
                        isinstance(vector, list) and vector for vector in vectors
                    )
                ):
                    return EmbeddingResult(
                        ok=False,
                        model=model.strip(),
                        error="Ollama no retornó embeddings válidos.",
                    )
                embeddings = [[float(value) for value in vector] for vector in vectors]
                result = EmbeddingResult(
                    ok=True,
                    model=str(parsed.get("model", model.strip())),
                    embeddings=embeddings,
                    total_duration=parsed.get("total_duration"),
                    load_duration=parsed.get("load_duration"),
                    prompt_eval_count=parsed.get("prompt_eval_count"),
                )
                self._observe(
                    {
                        "operation": "embed",
                        "endpoint": f"{self.base_url}/api/embed",
                        "requested_model": model.strip(),
                        "model_used": result.model,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        "total_duration": result.total_duration,
                        "load_duration": result.load_duration,
                        "prompt_eval_count": result.prompt_eval_count,
                        "embedding_count": len(result.embeddings),
                        "dimensions": result.dimensions,
                        "ok": True,
                        **self._device_report(result.model),
                    }
                )
                return result
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            ImportError,
            TypeError,
            ValueError,
        ) as exc:
            result = EmbeddingResult(ok=False, model=model.strip(), error=str(exc))
            self._observe(
                {
                    "operation": "embed",
                    "endpoint": f"{self.base_url}/api/embed",
                    "requested_model": model.strip(),
                    "model_used": model.strip(),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "ok": False,
                    "error": str(exc),
                }
            )
            return result

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
                models = [item.get("name") for item in parsed.get("models", [])]
                return {"ok": True, "base_url": self.base_url, "models": models}
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            ImportError,
        ) as exc:
            return {
                "ok": False,
                "base_url": self.base_url,
                "models": [],
                "error": str(exc),
            }


def check_ollama_cognitive_health(
    base_url: str = "http://127.0.0.1:11434",
    timeout: int = 5,
) -> dict[str, Any]:
    """Diagnóstico de Ollama como motor cognitivo local."""

    client = OllamaClient(base_url=base_url, timeout=timeout)
    started = time.perf_counter()
    health = client.health()
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    models = [str(model) for model in health.get("models", []) if model]
    router = ModelRouter(available_models=models)

    reasoning = router.route("central")
    coding = router.route("coder")
    embedding = router.route("embedding")
    lightweight = router.route("fast", prefer_speed=True)
    selected_reasoning = reasoning.selected_model
    selected_coding = coding.selected_model
    selected_embedding = embedding.selected_model
    selected_lightweight = lightweight.selected_model
    if not models:
        selected_reasoning = "qwen2.5:3b-instruct"
        selected_coding = "qwen2.5-coder:3b"
        selected_embedding = "nomic-embed-text:latest"
        selected_lightweight = "qwen3:4b"

    installed = set(models)
    reasoning_available = bool(health.get("ok")) and selected_reasoning in installed
    coder_available = bool(health.get("ok")) and selected_coding in installed
    embedding_available = bool(health.get("ok")) and selected_embedding in installed
    required_present = reasoning_available and embedding_available

    roles_by_model: dict[str, list[str]] = {}
    for role, decision in {
        "reasoning": selected_reasoning,
        "coding": selected_coding,
        "embedding": selected_embedding,
        "lightweight": selected_lightweight,
    }.items():
        roles_by_model.setdefault(decision, []).append(role)

    degraded_functions: list[str] = []
    if not health.get("ok"):
        degraded_functions = [
            "semantic_embedding",
            "neuron_nutrition",
            "learning_evaluation",
            "memory_diagnosis",
            "stable_consolidation",
        ]
    else:
        if not reasoning_available:
            degraded_functions.extend(
                [
                    "neuron_nutrition",
                    "learning_evaluation",
                    "memory_diagnosis",
                    "stable_consolidation",
                ]
            )
        if not embedding_available:
            degraded_functions.append("semantic_embedding")

    errors: list[str] = []
    if health.get("error"):
        errors.append(str(health["error"]))

    if not health.get("ok"):
        recommended_action = "Iniciar Ollama y confirmar que /api/tags responda."
    elif not embedding_available:
        recommended_action = (
            "Instalar un modelo de embeddings compatible, por ejemplo nomic-embed-text."
        )
    elif not reasoning_available:
        recommended_action = "Instalar un modelo de razonamiento recomendado, por ejemplo qwen2.5:3b-instruct."
    else:
        recommended_action = "Ollama listo como motor cognitivo local."

    return {
        "ok": bool(health.get("ok")),
        "base_url": health.get("base_url", base_url),
        "models_available": models,
        "models": models,
        "required_models_present": required_present,
        "embedding_model_available": embedding_available,
        "reasoning_model_available": reasoning_available,
        "coder_model_available": coder_available,
        "latency_ms": latency_ms,
        "errors": errors,
        "recommended_action": recommended_action,
        "selected_models": {
            "reasoning": selected_reasoning,
            "coding": selected_coding,
            "embeddings": selected_embedding,
            "lightweight": selected_lightweight,
        },
        "role_capabilities": roles_by_model,
        "degraded_functions": sorted(set(degraded_functions)),
        "mode": "full_local"
        if health.get("ok") and required_present
        else ("degraded_no_ollama" if not health.get("ok") else "partial_local"),
        "truth": "Sin Ollama, Tríade opera en observación/fallback; no consolida aprendizaje profundo automáticamente.",
    }
