"""Ollama adapter with safe fallback for Triade."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
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
