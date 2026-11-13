"""Contrato neutral para motores de inferencia locales.

Los módulos cognitivos dependen de este contrato y no de Ollama o llama.cpp.
Cada implementación conserva metadatos suficientes para la trazabilidad.
"""

from __future__ import annotations

from typing import Any, Protocol


class ModelProvider(Protocol):
    provider: str

    def generate(
        self,
        model: str,
        prompt: str,
        system: str | None = None,
        options: dict[str, Any] | None = None,
        *,
        use_active_peft: bool = False,
    ) -> Any: ...

    def embed(
        self,
        model: str,
        input_text: str | list[str],
        truncate: bool = True,
        dimensions: int | None = None,
    ) -> Any: ...

    def health(self) -> dict[str, Any]: ...
