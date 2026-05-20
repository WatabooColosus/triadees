"""N Creadora · órgano interno de diseño de neuronas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class NeuronSpec:
    name: str
    mission: str
    domain: str
    rules: list[str] = field(default_factory=list)
    status: str = "candidate"
    created_by: str = "neuron_creator"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NeuronCreator:
    """Diseña especificaciones de neuronas candidatas."""

    def create(self, name: str, mission: str, domain: str, rules: list[str] | None = None) -> NeuronSpec:
        clean_name = self._clean(name) or "neurona_candidata"
        clean_mission = self._clean(mission) or "Misión pendiente de definición."
        clean_domain = self._clean(domain) or "general"
        base_rules = [
            "Operar dentro del ciclo auditable de Tríade.",
            "No modificar memoria estable sin validación.",
            "Producir salidas verificables.",
        ]
        final_rules = base_rules + [self._clean(rule) for rule in (rules or []) if self._clean(rule)]
        return NeuronSpec(
            name=clean_name,
            mission=clean_mission,
            domain=clean_domain,
            rules=final_rules,
            status="candidate",
        )

    @staticmethod
    def _clean(value: str) -> str:
        return " ".join(str(value).strip().split())
