"""Cliente de llama.cpp sin dependencias Python pesadas.

Soporta el servidor HTTP compatible con OpenAI y, como fallback, un binario
``llama-cli``. Si el motor no está instalado devuelve un resultado degradado
trazable; nunca hace que el núcleo dependa de Ollama.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LlamaCppResult:
    ok: bool
    text: str
    model: str
    provider: str = "llama.cpp"
    error: str | None = None
    total_duration: int | None = None
    eval_count: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "model": self.model,
            "provider": self.provider,
            "error": self.error,
            "total_duration": self.total_duration,
            "eval_count": self.eval_count,
        }


class LlamaCppClient:
    provider = "llama.cpp"

    def __init__(
        self,
        base_url: str | None = None,
        model_path: str | None = None,
        executable: str | None = None,
        timeout: int = 120,
    ) -> None:
        self.base_url = (base_url or os.getenv("TRIADE_LLAMA_CPP_URL", "")).rstrip("/")
        self.model_path = model_path or os.getenv("TRIADE_LLAMA_CPP_MODEL", "")
        self.executable = executable or os.getenv("TRIADE_LLAMA_CPP_BIN", "llama-cli")
        self.timeout = timeout

    def _prompt(self, prompt: str, system: str | None) -> str:
        return f"{system.strip()}\n\n{prompt}" if system else prompt

    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
        *,
        use_active_peft: bool = False,
    ) -> LlamaCppResult:
        del use_active_peft
        started = time.perf_counter()
        if self.base_url:
            payload: dict[str, Any] = {
                "model": model,
                "prompt": prompt,
                "stream": False,
            }
            if system:
                payload["system"] = system
            if options:
                payload["options"] = dict(options)
            request = urllib.request.Request(
                f"{self.base_url}/v1/chat/completions",
                data=json.dumps(
                    {
                        **payload,
                        "messages": (
                            [{"role": "system", "content": system}] if system else []
                        )
                        + [{"role": "user", "content": prompt}],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    parsed = json.loads(response.read().decode("utf-8"))
                choices = parsed.get("choices") or []
                text = (
                    str((choices[0].get("message") or {}).get("content", ""))
                    if choices
                    else str(parsed.get("response", ""))
                )
                return LlamaCppResult(
                    True,
                    text.strip(),
                    model,
                    total_duration=round(
                        (time.perf_counter() - started) * 1_000_000_000
                    ),
                )
            except (
                urllib.error.URLError,
                TimeoutError,
                OSError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                return LlamaCppResult(False, "", model, error=str(exc))

        if not self.model_path:
            return LlamaCppResult(
                False,
                "",
                model,
                error="llama.cpp no configurado: falta TRIADE_LLAMA_CPP_MODEL o TRIADE_LLAMA_CPP_URL",
            )
        command = [
            self.executable,
            "-m",
            self.model_path,
            "-p",
            self._prompt(prompt, system),
            "-n",
            str(int((options or {}).get("num_predict", 256))),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return LlamaCppResult(False, "", model, error=str(exc))
        if completed.returncode != 0:
            return LlamaCppResult(
                False,
                "",
                model,
                error=(completed.stderr or f"exit_{completed.returncode}").strip(),
            )
        return LlamaCppResult(
            True,
            completed.stdout.strip(),
            model,
            total_duration=round((time.perf_counter() - started) * 1_000_000_000),
        )

    def embed(
        self,
        model: str,
        input_text: str | list[str],
        truncate: bool = True,
        dimensions: int | None = None,
    ) -> Any:
        del truncate, dimensions
        from triade.models.ollama_client import EmbeddingResult

        return EmbeddingResult(
            False, model=model, error="llama.cpp no expone embeddings por este contrato"
        )

    def health(self) -> dict[str, Any]:
        if not self.base_url:
            return {
                "ok": bool(self.model_path),
                "provider": self.provider,
                "base_url": None,
                "models": [self.model_path] if self.model_path else [],
                "error": None if self.model_path else "llama.cpp no configurado",
            }
        request = urllib.request.Request(f"{self.base_url}/health", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return {
                    "ok": 200 <= response.status < 300,
                    "provider": self.provider,
                    "base_url": self.base_url,
                    "models": [self.model_path] if self.model_path else [],
                    "error": None,
                }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {
                "ok": False,
                "provider": self.provider,
                "base_url": self.base_url,
                "models": [],
                "error": str(exc),
            }
