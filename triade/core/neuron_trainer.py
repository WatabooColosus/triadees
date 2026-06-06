"""N Formadora · órgano interno de evaluación de neuronas.

La N Formadora evalúa, limita y recomienda estado.
No consolida neuronas estables automáticamente.
"""

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
    required_human_review: bool = True
    policy: str = "trainer_recommends_human_approves"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NeuronTrainer:
    """Evalúa neuronas candidatas y asigna estado operativo no estable."""

    def evaluate(self, spec: NeuronSpec) -> NeuronTrainingResult:
        score = 0.0
        strengths: list[str] = []
        warnings: list[str] = []
        recommendations: list[str] = []

        if spec.name and len(spec.name) >= 4:
            score += 0.12
            strengths.append("Nombre identificable.")
        else:
            warnings.append("Nombre demasiado corto o vacío.")

        if spec.mission and len(spec.mission) >= 30:
            score += 0.18
            strengths.append("Misión descriptiva.")
        else:
            warnings.append("Misión insuficiente.")
            recommendations.append("Ampliar misión con objetivo, límites y utilidad.")

        if spec.domain:
            score += 0.10
            strengths.append("Dominio asignado.")

        if len(spec.rules) >= 5:
            score += 0.14
            strengths.append("Reglas operativas suficientes.")
        else:
            warnings.append("Faltan reglas de operación.")

        if spec.triggers:
            score += 0.10
            strengths.append("Triggers definidos.")
        else:
            warnings.append("Sin triggers de activación.")

        if spec.inputs_allowed and spec.outputs_allowed:
            score += 0.12
            strengths.append("Entradas y salidas permitidas definidas.")
        else:
            warnings.append("Faltan entradas/salidas permitidas.")

        if spec.forbidden_actions and any("bypass_safety" in x for x in spec.forbidden_actions):
            score += 0.12
            strengths.append("Acciones prohibidas críticas presentes.")
        else:
            warnings.append("Faltan prohibiciones críticas.")

        if spec.success_metrics:
            score += 0.10
            strengths.append("Métricas de éxito definidas.")
        else:
            warnings.append("Sin métricas de éxito.")

        if spec.evidence_required:
            score += 0.12
            strengths.append("Evidencia requerida definida.")
        else:
            warnings.append("Sin evidencia requerida.")

        score = round(min(score, 1.0), 2)

        # Regla de seguridad: nunca estable automáticamente.
        if score >= 0.80:
            status = "experimental_candidate"
            recommendations.append("Puede pasar a revisión humana antes de operar como experimental.")
        elif score >= 0.55:
            status = "candidate"
            recommendations.append("Mantener como candidata y completar evidencia/pruebas.")
        elif score >= 0.30:
            status = "weak_candidate"
            recommendations.append("Reformular misión, triggers y métricas antes de usar.")
        else:
            status = "rejected"

        recommendations.append("No consolidar como estable sin aprobación humana, pruebas y evidencia repetida.")

        return NeuronTrainingResult(
            name=spec.name,
            score=score,
            status=status,
            strengths=strengths,
            warnings=warnings,
            recommendations=recommendations,
            required_human_review=True,
        )
