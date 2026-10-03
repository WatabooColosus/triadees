"""Fábrica de motores cognitivos locales reemplazables."""

from __future__ import annotations

from pathlib import Path

from triade.models.ollama_client import OllamaClient


def normalize_model_provider(provider: str | None) -> str:
    clean = str(provider or "ollama").strip().lower()
    aliases = {
        "llamacpp": "llama.cpp",
        "llama_cpp": "llama.cpp",
        "llama-cpp": "llama.cpp",
    }
    return aliases.get(clean, clean)


def default_model_base_url(provider: str) -> str:
    provider = normalize_model_provider(provider)
    if provider == "llama.cpp":
        return "http://127.0.0.1:8080"
    return "http://127.0.0.1:11434"


def build_model_client(
    provider: str,
    *,
    base_url: str | None = None,
    timeout: int = 60,
    db_path: str | Path | None = None,
) -> OllamaClient | None:
    normalized = normalize_model_provider(provider)
    resolved_url = base_url or default_model_base_url(normalized)
    if normalized == "ollama":
        return OllamaClient(
            base_url=resolved_url,
            timeout=timeout,
            db_path=db_path,
        )
    if normalized == "llama.cpp":
        from triade.models.llamacpp_client import LlamaCppClient

        return LlamaCppClient(
            base_url=resolved_url,
            timeout=timeout,
            db_path=db_path,
        )
    return None
