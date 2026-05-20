"""N Formadora · órgano interno de evaluación de neuronas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .neuron_creator import NeuronSpec


@dataclass(slots=True)
class NeuronTrainingResult:
    name: str
    score: float
    status: str
    strengths: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NeuronTrainer:
    """Evalúa neuronas candidatas y asigna estado operativo."""

    def evaluate(self, spec: NeuronSpec) -> NeuronTrainingResult:
        score = 0.0
        strengths: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []

        if spec.name and len(spec.name) >= 4:
            score += 0.20
            strengths.append("Nombre identificable.")
        else:
            warnings.append("Nombre demasiado corto o vacío.")

        if spec.mission and len(spec.mission) >= 20:
            score += 0.30
            strengths.append("Misión suficientemente descriptiva.")
        else:
            warnings.append("Misión insuficiente.")
            recommendations.append("Ampliar misión con objetivo, límites y utilidad.")

        if spec.domain:
            score += 0.15
            strengths.append("Dominio asignado.")

        if len(spec.rules) >= 3:
            score += 0.25
            strengths.append("Reglas mínimas presentes.")
        else:
            warnings.append("Faltan reglas de operación.")

        if any("verific" in rule.lower() for rule in spec.rules):
            score += 0.10
            strengths.append("Incluye orientación verificable.")

        score = round(min(score, 1.0), 2)
        if score >= 0.85:
            status = "stable"
        elif score >= 0.60:
            status = "experimental"
        elif score >= 0.35:
            status = "candidate"
        else:
            status = "rejected"

        if status != "stable":
            recommendations.append("Mantener en evaluación antes de consolidar como neurona estable.")

        return NeuronTrainingResult(
            name=spec.name,
            score=score,
            status=status,
            strengths=strengths,
            warnings=warnings,
            recommendations=recommendations,
        )
