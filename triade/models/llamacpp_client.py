"""Cliente ligero para llama.cpp server compatible con el contrato de OllamaClient.

No enlaza libllama dentro del proceso de Tríade: usa el servidor HTTP de
llama.cpp para que el modelo pueda vivir/morir fuera del núcleo Python.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from triade.models.ollama_client import EmbeddingResult, ModelResult, OllamaClient


class LlamaCppClient(OllamaClient):
    """Adaptador HTTP para llama.cpp server.

    Hereda el tipo de OllamaClient para conservar compatibilidad con los
    consumidores existentes (Central, Hipotálamo y memoria) mientras el runtime
    migra hacia un contrato de proveedor más general.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        timeout: int = 60,
        event_callback=None,
        db_path: str | Path | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            timeout=timeout,
            event_callback=event_callback,
            db_path=db_path,
            keep_alive=None,
        )

    def health(self) -> dict[str, Any]:
        request = urllib.request.Request(f"{self.base_url}/v1/models", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            models = [
                str(item.get("id"))
                for item in parsed.get("data", [])
                if isinstance(item, dict) and item.get("id")
            ]
            return {
                "ok": True,
                "base_url": self.base_url,
                "models": models,
                "provider": "llama.cpp",
            }
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            return {
                "ok": False,
                "base_url": self.base_url,
                "models": [],
                "provider": "llama.cpp",
                "error": str(exc),
            }

    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
        *,
        keep_alive: str | int | None = None,
        use_active_peft: bool = False,
    ) -> ModelResult:
        del keep_alive, use_active_peft
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        options = dict(options or {})
        for key in ("temperature", "top_p", "seed"):
            if key in options:
                payload[key] = options[key]
        if "num_predict" in options:
            payload["max_tokens"] = int(options["num_predict"])
        elif "max_tokens" in options:
            payload["max_tokens"] = int(options["max_tokens"])

        request = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            choices = parsed.get("choices") or []
            first = choices[0] if choices and isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first, dict) else {}
            content = (
                str(message.get("content") or "")
                if isinstance(message, dict)
                else ""
            ).strip()
            usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
            result = ModelResult(
                ok=bool(content),
                text=content,
                model=str(parsed.get("model") or model),
                provider="llama.cpp",
                error=None if content else "llama.cpp devolvió una respuesta vacía.",
                prompt_eval_count=usage.get("prompt_tokens"),
                eval_count=usage.get("completion_tokens"),
            )
            self._observe(
                {
                    "operation": "generate",
                    "endpoint": f"{self.base_url}/v1/chat/completions",
                    "requested_model": model,
                    "model_used": result.model,
                    "provider": "llama.cpp",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "prompt_eval_count": result.prompt_eval_count,
                    "eval_count": result.eval_count,
                    "ok": result.ok,
                }
            )
            return result
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            self._observe(
                {
                    "operation": "generate",
                    "endpoint": f"{self.base_url}/v1/chat/completions",
                    "requested_model": model,
                    "provider": "llama.cpp",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "ok": False,
                    "error": str(exc),
                }
            )
            return ModelResult(
                ok=False,
                text="",
                model=model,
                provider="llama.cpp",
                error=str(exc),
            )

    def embed(
        self,
        model: str,
        input_text: str | list[str],
        truncate: bool = True,
        dimensions: int | None = None,
        *,
        keep_alive: str | int | None = None,
    ) -> EmbeddingResult:
        del truncate, keep_alive
        if isinstance(input_text, str) and not input_text.strip():
            return EmbeddingResult(
                ok=False, model=model, provider="llama.cpp", error="empty_input"
            )
        if isinstance(input_text, list) and not input_text:
            return EmbeddingResult(
                ok=False, model=model, provider="llama.cpp", error="empty_input"
            )

        payload: dict[str, Any] = {
            "model": model,
            "input": input_text,
            "encoding_format": "float",
        }
        if dimensions is not None:
            payload["dimensions"] = int(dimensions)

        request = urllib.request.Request(
            f"{self.base_url}/v1/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
            data = parsed.get("data") or []
            vectors = [
                [float(value) for value in item.get("embedding", [])]
                for item in data
                if isinstance(item, dict) and item.get("embedding")
            ]
            if not vectors:
                return EmbeddingResult(
                    ok=False,
                    model=model,
                    provider="llama.cpp",
                    error="llama.cpp no retornó embeddings válidos.",
                )
            usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
            result = EmbeddingResult(
                ok=True,
                model=str(parsed.get("model") or model),
                embeddings=vectors,
                provider="llama.cpp",
                prompt_eval_count=usage.get("prompt_tokens"),
            )
            self._observe(
                {
                    "operation": "embed",
                    "endpoint": f"{self.base_url}/v1/embeddings",
                    "requested_model": model,
                    "model_used": result.model,
                    "provider": "llama.cpp",
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "embedding_count": len(vectors),
                    "dimensions": result.dimensions,
                    "ok": True,
                }
            )
            return result
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            OSError,
            TypeError,
            ValueError,
            KeyError,
        ) as exc:
            return EmbeddingResult(
                ok=False,
                model=model,
                provider="llama.cpp",
                error=str(exc),
            )
