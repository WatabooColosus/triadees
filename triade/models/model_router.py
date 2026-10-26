"""Model Router · selección de modelos por rol, tarea y hardware.

Fase 1.7B: recomienda modelos Ollama disponibles considerando rol,
intención, urgencia y capacidad del sistema.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from .hardware_profile import HardwareProfile


@dataclass(slots=True)
class ModelRouteDecision:
    role: str
    selected_model: str
    provider: str = "ollama"
    reason: str = ""
    fallback_used: bool = False
    candidates: list[str] = field(default_factory=list)
    hardware_tier: str = "unknown"
    rejected_by_hardware: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelRouter:
    """Recomienda modelos por rol según disponibilidad, intención y hardware."""

    DEFAULTS: ClassVar = {
        "planner": ["qwen3:4b", "qwen2.5:3b-instruct"],
        "critic": ["qwen3:4b", "qwen2.5:3b-instruct"],
        "evaluator": ["qwen3:4b", "qwen2.5:3b-instruct"],
        "vision": ["gemma3:4b"],
        "summarizer": ["qwen3:1.7b", "qwen2.5:3b-instruct"],
        "hypothalamus": [
            "qwen2.5:1.5b",
            "qwen2.5:3b-instruct",
            "qwen3:1.7b",
            "qwen3:4b",
        ],
        "central": [
            "qwen2.5:1.5b",
            "qwen2.5:3b-instruct",
            "llama3:latest",
            "llama3.1:8b",
            "qwen3:4b",
        ],
        "creator": ["qwen2.5:3b-instruct", "qwen3:4b", "llama3:latest"],
        "trainer": ["qwen2.5:3b-instruct", "qwen3:4b", "llama3:latest"],
        "coder": ["qwen2.5-coder:3b", "qwen2.5-coder:1.5b-base", "qwen2.5:3b-instruct"],
        "embedding": ["nomic-embed-text:latest", "qwen3-embedding:0.6b"],
        "fast": ["qwen2.5:1.5b", "qwen3:1.7b", "qwen2.5:3b-instruct", "qwen3:4b"],
        "deep": ["llama3.1:8b", "llama3:latest", "qwen3:4b", "qwen2.5:3b-instruct"],
    }

    MODEL_RAM_GB: ClassVar = {
        "qwen3:1.7b": 2.5,
        "qwen2.5:1.5b": 1.8,
        "qwen2.5-coder:1.5b-base": 2.5,
        "qwen2.5:3b-instruct": 4.0,
        "qwen2.5-coder:3b": 4.0,
        "qwen3:4b": 5.5,
        "deepseek-coder-v2:16b": 12.0,
        "llama3:latest": 7.0,
        "llama3.1:8b": 8.5,
        "llama3.2:3b": 4.0,
        "llama3.2:1b": 2.0,
        "nomic-embed-text:latest": 1.0,
        "qwen3-embedding:0.6b": 1.0,
    }

    @staticmethod
    def _estimate_ram(model: str) -> float:
        """Estima RAM requerida para modelos no listados por convención de nombre."""
        known = ModelRouter.MODEL_RAM_GB.get(model)
        if known is not None:
            return known
        # Estimar desde el nombre: qwen3:4b → 4B params → ~2x en GB
        import re

        match = re.search(r"(?:[:\-])(\d+)b", model)
        if match:
            params_b = int(match.group(1))
            return max(1.0, params_b * 1.8)  # ~1.8GB por cada 1B params
        return 4.0  # fallback conservador

    def __init__(
        self,
        available_models: list[str] | None = None,
        hardware: HardwareProfile | None = None,
        provider: str | None = None,
    ) -> None:
        self.available_models = available_models or []
        self.hardware = hardware
        self.provider = (
            provider or os.getenv("TRIADE_MODEL_PROVIDER", "ollama") or "ollama"
        ).strip()

    def route(
        self,
        role: str,
        intent: str = "conversation",
        urgency: str = "medium",
        prefer_speed: bool = False,
        prefer_depth: bool = False,
    ) -> ModelRouteDecision:
        normalized_role = self._normalize_role(role, intent, prefer_speed, prefer_depth)
        measured = self._measured_route(normalized_role)
        if measured is not None:
            return measured
        candidates = self.DEFAULTS.get(normalized_role, self.DEFAULTS["central"])
        hardware_candidates, rejected = self._filter_by_hardware(candidates)
        selected = self._first_available(hardware_candidates)
        hardware_tier = self.hardware.tier if self.hardware else "unknown"

        if selected:
            return ModelRouteDecision(
                role=normalized_role,
                selected_model=selected,
                provider=self.provider,
                reason=self._reason(
                    normalized_role,
                    selected,
                    urgency,
                    prefer_speed,
                    prefer_depth,
                    hardware_tier,
                ),
                fallback_used=False,
                candidates=hardware_candidates,
                hardware_tier=hardware_tier,
                rejected_by_hardware=rejected,
            )

        if normalized_role == "embedding":
            fallback = "disabled:embedding-on-demand"
            fallback_reason = "No hay un modelo de embeddings instalado; embeddings quedan bajo demanda."
        else:
            compatible_fallback = self._first_compatible_fallback(normalized_role)
            if compatible_fallback is not None:
                fallback = compatible_fallback
                fallback_reason = (
                    f"Ningún candidato recomendado para {normalized_role} está instalado; "
                    f"se usó {fallback} como fallback generativo compatible."
                )
            else:
                fallback = "unavailable:no-generative-model-installed"
                fallback_reason = (
                    "No hay un modelo generativo compatible instalado para este rol."
                )
        return ModelRouteDecision(
            role=normalized_role,
            selected_model=fallback,
            provider=self.provider,
            reason=fallback_reason,
            fallback_used=True,
            candidates=hardware_candidates,
            hardware_tier=hardware_tier,
            rejected_by_hardware=rejected,
        )

    def _measured_route(self, role: str) -> ModelRouteDecision | None:
        configured = os.getenv(
            "TRIADE_MEASURED_ROUTING_PATH", "triade/models/active_routing.json"
        )
        path = Path(configured)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        if payload.get("status") != "active" or not payload.get("evidence_ref"):
            return None
        routes = payload.get("routes")
        if not isinstance(routes, dict):
            return None
        selected = routes.get(role)
        if not isinstance(selected, str) or selected not in self.available_models:
            return None
        if not self._model_fits(selected):
            return None
        if role != "embedding" and self._is_embedding_model(selected):
            return None
        return ModelRouteDecision(
            role=role,
            selected_model=selected,
            provider=self.provider,
            reason=f"measured_ab_route:{payload.get('benchmark_sha256', 'unknown')}",
            fallback_used=False,
            candidates=[selected],
            hardware_tier=self.hardware.tier if self.hardware else "unknown",
            rejected_by_hardware=[],
        )

    def route_many(
        self, intent: str = "conversation", urgency: str = "medium"
    ) -> dict[str, Any]:
        prefer_speed = urgency == "high"
        prefer_depth = intent in {"analyze", "memory", "build_or_update"}
        roles = [
            "hypothalamus",
            "central",
            "creator",
            "trainer",
            "coder",
            "embedding",
            "fast",
            "deep",
        ]
        return {
            "available_models": self.available_models,
            "hardware": self.hardware.to_dict() if self.hardware else None,
            "intent": intent,
            "urgency": urgency,
            "decisions": {
                role: self.route(
                    role,
                    intent=intent,
                    urgency=urgency,
                    prefer_speed=prefer_speed,
                    prefer_depth=prefer_depth,
                ).to_dict()
                for role in roles
            },
        }

    def _filter_by_hardware(self, candidates: list[str]) -> tuple[list[str], list[str]]:
        if self.hardware is None:
            return candidates, []
        allowed: list[str] = []
        rejected: list[str] = []
        for model in candidates:
            if self._model_fits(model):
                allowed.append(model)
            else:
                rejected.append(model)
        return allowed or candidates[-2:], rejected

    def _model_fits(self, model: str) -> bool:
        if self.hardware is None:
            return True
        required = self._estimate_ram(model)
        available = self.hardware.ram_available_gb
        tier = self.hardware.tier
        if model in {"nomic-embed-text:latest", "qwen3-embedding:0.6b"}:
            return True
        if tier == "low":
            return required <= 4.0 and available >= 2.0
        if tier == "medium":
            return required <= 8.5 and available >= min(required, 5.0)
        if tier == "high":
            return available >= min(required, 6.0)
        return available == 0.0 or available >= required

    def _first_available(self, candidates: list[str]) -> str | None:
        installed = set(self.available_models)
        for model in candidates:
            if model in installed:
                return model
        return None

    @staticmethod
    def _is_embedding_model(model: str) -> bool:
        return "embed" in model.lower()

    def _first_compatible_fallback(self, role: str) -> str | None:
        eligible = [
            model
            for model in set(self.available_models)
            if not self._is_embedding_model(model)
            and (role == "coder" or "coder" not in model.lower())
            and self._model_fits(model)
        ]
        if role == "coder":
            eligible.sort(
                key=lambda model: (
                    "coder" not in model.lower(),
                    self._estimate_ram(model),
                    model,
                )
            )
        elif role == "deep":
            eligible.sort(key=lambda model: (-self._estimate_ram(model), model))
        else:
            eligible.sort(key=lambda model: (self._estimate_ram(model), model))
        return eligible[0] if eligible else None

    @staticmethod
    def _normalize_role(
        role: str, intent: str, prefer_speed: bool, prefer_depth: bool
    ) -> str:
        clean = (role or "central").strip().lower()
        aliases = {
            "hipotalamo": "hypothalamus",
            "hipotálamo": "hypothalamus",
            "central": "central",
            "creadora": "creator",
            "formadora": "trainer",
            "codigo": "coder",
            "código": "coder",
            "memoria": "embedding",
            "rapido": "fast",
            "rápido": "fast",
            "profundo": "deep",
            "planificador": "planner",
            "crítico": "critic",
            "critico": "critic",
            "evaluador": "evaluator",
            "visión": "vision",
            "vision": "vision",
            "resumidor": "summarizer",
        }
        clean = aliases.get(clean, clean)
        if prefer_speed and clean == "central":
            return "fast"
        if prefer_depth and clean == "central":
            return "deep"
        if intent == "build_or_update" and clean == "central":
            return "creator"
        return clean if clean in ModelRouter.DEFAULTS else "central"

    @staticmethod
    def _reason(
        role: str,
        model: str,
        urgency: str,
        prefer_speed: bool,
        prefer_depth: bool,
        hardware_tier: str,
    ) -> str:
        hw = f" Perfil hardware={hardware_tier}."
        if role == "fast" or prefer_speed:
            return f"Seleccionado {model} por prioridad de velocidad/urgencia {urgency}.{hw}"
        if role == "deep" or prefer_depth:
            return f"Seleccionado {model} por prioridad de profundidad analítica compatible con el sistema.{hw}"
        if role == "coder":
            return f"Seleccionado {model} por tarea relacionada con código.{hw}"
        if role == "embedding":
            return f"Seleccionado {model} para memoria semántica o embeddings.{hw}"
        return (
            f"Seleccionado {model} como mejor candidato disponible para rol {role}.{hw}"
        )
