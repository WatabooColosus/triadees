"""Matriz de compatibilidad de modelos para Tríade Ω.

Clasifica modelos como recommended, allowed, risky o blocked según hardware,
RAM/VRAM y disponibilidad local.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .hardware_profile import HardwareProfile
from .model_router import ModelRouter


@dataclass(slots=True)
class ModelCompatibility:
    model: str
    status: str
    installed: bool
    estimated_ram_gb: float
    recommended_roles: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelCompatibilityMatrix:
    """Evalúa compatibilidad de modelos con la máquina local."""

    ALL_MODELS = sorted(set(ModelRouter.MODEL_RAM_GB.keys()))

    ROLE_HINTS = {
        "qwen3:1.7b": ["fast"],
        "qwen2.5-coder:1.5b-base": ["coder", "fast"],
        "qwen2.5:3b-instruct": ["hypothalamus", "central", "creator", "trainer"],
        "qwen2.5-coder:3b": ["coder"],
        "qwen3:4b": ["central", "creator", "trainer", "deep"],
        "llama3:latest": ["central", "deep"],
        "llama3.1:8b": ["deep", "central"],
        "nomic-embed-text:latest": ["embedding"],
        "qwen3-embedding:0.6b": ["embedding"],
    }

    def __init__(self, hardware: HardwareProfile, available_models: list[str] | None = None) -> None:
        self.hardware = hardware
        self.available_models = available_models or []

    def evaluate_model(self, model: str) -> ModelCompatibility:
        installed = model in set(self.available_models)
        estimated_ram = ModelRouter.MODEL_RAM_GB.get(model, 4.0)
        reasons: list[str] = []
        warnings: list[str] = []

        if not installed:
            warnings.append("Modelo no instalado en Ollama.")

        if model in {"nomic-embed-text:latest", "qwen3-embedding:0.6b"}:
            status = "recommended" if installed else "allowed"
            reasons.append("Modelo liviano para embeddings/memoria semántica.")
            return ModelCompatibility(model, status, installed, estimated_ram, self.ROLE_HINTS.get(model, []), reasons, warnings)

        ram = self.hardware.ram_available_gb
        tier = self.hardware.tier
        max_vram = max((gpu.vram_total_gb for gpu in self.hardware.gpus), default=0.0)
        cuda = any(gpu.cuda_available for gpu in self.hardware.gpus)

        if ram < 2.0:
            status = "blocked"
            warnings.append("RAM disponible crítica para modelos locales.")
        elif estimated_ram > ram + 1.0:
            status = "blocked"
            warnings.append("RAM disponible insuficiente frente al consumo estimado.")
        elif tier == "low" and estimated_ram > 4.0:
            status = "risky"
            warnings.append("Hardware low; modelo pesado para esta máquina.")
        elif tier == "medium" and estimated_ram <= 4.0:
            status = "recommended"
            reasons.append("Buen equilibrio entre capacidad y consumo para hardware medium.")
        elif tier == "medium" and estimated_ram <= 8.5:
            status = "allowed"
            reasons.append("Modelo permitido si no hay alta carga del sistema.")
        elif tier == "high":
            status = "recommended" if estimated_ram <= 8.5 else "allowed"
            reasons.append("Hardware high compatible con modelos medianos/profundos.")
        else:
            status = "allowed"
            reasons.append("Modelo compatible con restricciones conservadoras.")

        if cuda:
            reasons.append("CUDA detectado; posible aceleración NVIDIA.")
        elif max_vram > 0:
            reasons.append("GPU detectada, pero CUDA no confirmada.")
        else:
            warnings.append("Sin VRAM detectada; uso esperado por CPU/RAM.")

        if not installed and status == "recommended":
            status = "allowed"

        return ModelCompatibility(model, status, installed, estimated_ram, self.ROLE_HINTS.get(model, []), reasons, warnings)

    def build(self) -> dict[str, Any]:
        models = [self.evaluate_model(model).to_dict() for model in self.ALL_MODELS]
        counts: dict[str, int] = {"recommended": 0, "allowed": 0, "risky": 0, "blocked": 0}
        for item in models:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        return {
            "hardware": self.hardware.to_dict(),
            "available_models": self.available_models,
            "counts": counts,
            "models": models,
            "summary": self._summary(counts),
        }

    @staticmethod
    def _summary(counts: dict[str, int]) -> str:
        if counts.get("recommended", 0) >= 3:
            return "Máquina apta para varios modelos locales recomendados."
        if counts.get("allowed", 0) >= 3:
            return "Máquina funcional con selección moderada de modelos."
        if counts.get("risky", 0) > counts.get("recommended", 0):
            return "Máquina limitada; priorizar modelos pequeños y fallback."
        return "Compatibilidad básica disponible; revisar RAM/VRAM antes de modelos pesados."
