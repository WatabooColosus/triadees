"""Construcción centralizada de proveedores de modelos."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .llamacpp_client import LlamaCppClient
from .model_provider import ModelProvider
from .ollama_client import OllamaClient


def create_model_client(
    provider: str | None = None,
    *,
    base_url: str | None = None,
    timeout: int = 60,
    db_path: str | Path | None = None,
    **kwargs: Any,
) -> ModelProvider:
    selected = (provider or os.getenv("TRIADE_MODEL_PROVIDER", "ollama")).strip().lower()
    if selected in {"llama.cpp", "llamacpp", "llama_cpp"}:
        return LlamaCppClient(base_url=base_url, timeout=timeout, **kwargs)
    if selected != "ollama":
        raise ValueError(f"Proveedor de modelo no soportado: {selected}")
    return OllamaClient(base_url=base_url or "http://127.0.0.1:11434", timeout=timeout, db_path=db_path)
