"""Model Router · selección de modelos por rol y tarea.

Fase 1.6: recomienda modelos Ollama disponibles sin modificar todavía
el ciclo principal. Sirve como órgano de decisión para Hipotálamo, Central,
Creadora, Formadora, código, embeddings y modo rápido.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelRouteDecision:
    role: str
    selected_model: str
    provider: str = "ollama"
    reason: str = ""
    fallback_used: bool = False
    candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelRouter:
    """Recomienda modelos por rol según disponibilidad e intención."""

    DEFAULTS = {
        "hypothalamus": ["qwen2.5:3b-instruct", "qwen3:1.7b", "qwen3:4b"],
        "central": ["qwen2.5:3b-instruct", "llama3:latest", "llama3.1:8b", "qwen3:4b"],
        "creator": ["qwen2.5:3b-instruct", "qwen3:4b", "llama3:latest"],
        "trainer": ["qwen2.5:3b-instruct", "qwen3:4b", "llama3:latest"],
        "coder": ["qwen2.5-coder:3b", "qwen2.5-coder:1.5b-base", "qwen2.5:3b-instruct"],
        "embedding": ["nomic-embed-text:latest", "qwen3-embedding:0.6b"],
        "fast": ["qwen3:1.7b", "qwen2.5:3b-instruct", "qwen3:4b"],
        "deep": ["llama3.1:8b", "llama3:latest", "qwen3:4b", "qwen2.5:3b-instruct"],
    }

    def __init__(self, available_models: list[str] | None = None) -> None:
        self.available_models = available_models or []

    def route(
        self,
        role: str,
        intent: str = "conversation",
        urgency: str = "medium",
        prefer_speed: bool = False,
        prefer_depth: bool = False,
    ) -> ModelRouteDecision:
        normalized_role = self._normalize_role(role, intent, prefer_speed, prefer_depth)
        candidates = self.DEFAULTS.get(normalized_role, self.DEFAULTS["central"])
        selected = self._first_available(candidates)

        if selected:
            return ModelRouteDecision(
                role=normalized_role,
                selected_model=selected,
                reason=self._reason(normalized_role, selected, urgency, prefer_speed, prefer_depth),
                fallback_used=False,
                candidates=candidates,
            )

        fallback = candidates[-1] if candidates else "qwen2.5:3b-instruct"
        return ModelRouteDecision(
            role=normalized_role,
            selected_model=fallback,
            reason="No se encontró candidato instalado; se recomienda fallback configurado.",
            fallback_used=True,
            candidates=candidates,
        )

    def route_many(self, intent: str = "conversation", urgency: str = "medium") -> dict[str, Any]:
        prefer_speed = urgency == "high"
        prefer_depth = intent in {"analyze", "memory", "build_or_update"}
        roles = ["hypothalamus", "central", "creator", "trainer", "coder", "embedding", "fast", "deep"]
        return {
            "available_models": self.available_models,
            "intent": intent,
            "urgency": urgency,
            "decisions": {
                role: self.route(role, intent=intent, urgency=urgency, prefer_speed=prefer_speed, prefer_depth=prefer_depth).to_dict()
                for role in roles
            },
        }

    def _first_available(self, candidates: list[str]) -> str | None:
        installed = set(self.available_models)
        for model in candidates:
            if model in installed:
                return model
        return None

    @staticmethod
    def _normalize_role(role: str, intent: str, prefer_speed: bool, prefer_depth: bool) -> str:
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
    def _reason(role: str, model: str, urgency: str, prefer_speed: bool, prefer_depth: bool) -> str:
        if role == "fast" or prefer_speed:
            return f"Seleccionado {model} por prioridad de velocidad/urgencia {urgency}."
        if role == "deep" or prefer_depth:
            return f"Seleccionado {model} por prioridad de profundidad analítica."
        if role == "coder":
            return f"Seleccionado {model} por tarea relacionada con código."
        if role == "embedding":
            return f"Seleccionado {model} para memoria semántica o embeddings."
        return f"Seleccionado {model} como mejor candidato disponible para rol {role}."
