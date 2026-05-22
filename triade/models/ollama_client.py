"""Ollama adapter with safe fallback for Tríade."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelResult:
    ok: bool
    text: str
    model: str
    provider: str = "ollama"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "model": self.model,
            "provider": self.provider,
            "error": self.error,
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

    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def generate(self, model: str, prompt: str, system: str | None = None) -> ModelResult:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
                return ModelResult(
                    ok=True,
                    text=str(parsed.get("response", "")).strip(),
                    model=model,
                )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            return ModelResult(
                ok=False,
                text="",
                model=model,
                error=str(exc),
            )

    def embed(
        self,
        model: str,
        input_text: str | list[str],
        truncate: bool = True,
        dimensions: int | None = None,
    ) -> EmbeddingResult:
        """Genera embeddings mediante el endpoint local POST /api/embed."""
        if not model.strip():
            return EmbeddingResult(ok=False, model=model, error="Debe especificarse el modelo de embedding.")
        if isinstance(input_text, str):
            if not input_text.strip():
                return EmbeddingResult(ok=False, model=model, error="El texto para embedding no puede estar vacío.")
        elif not input_text or not all(str(item).strip() for item in input_text):
            return EmbeddingResult(ok=False, model=model, error="Los textos para embedding no pueden estar vacíos.")

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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                vectors = parsed.get("embeddings", [])
                if not isinstance(vectors, list) or not vectors or not all(isinstance(vector, list) and vector for vector in vectors):
                    return EmbeddingResult(ok=False, model=model.strip(), error="Ollama no retornó embeddings válidos.")
                embeddings = [[float(value) for value in vector] for vector in vectors]
                return EmbeddingResult(
                    ok=True,
                    model=str(parsed.get("model", model.strip())),
                    embeddings=embeddings,
                    total_duration=parsed.get("total_duration"),
                    load_duration=parsed.get("load_duration"),
                    prompt_eval_count=parsed.get("prompt_eval_count"),
                )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            return EmbeddingResult(ok=False, model=model.strip(), error=str(exc))

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
                models = [item.get("name") for item in parsed.get("models", [])]
                return {"ok": True, "base_url": self.base_url, "models": models}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            return {"ok": False, "base_url": self.base_url, "models": [], "error": str(exc)}
