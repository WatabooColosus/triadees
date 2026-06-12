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
    required_human_review: bool = False
    policy: str = "trainer_auto_approves"

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

        mission_text = " ".join([
            spec.name or "",
            spec.mission or "",
            spec.domain or "",
        ]).lower()
        if self._looks_like_literal_question(mission_text):
            score -= 0.20
            warnings.append("La misión parece una pregunta factual simple; no debe convertirse en neurona literal.")
            recommendations.append("Reformular como necesidad operativa repetible o misión de aprendizaje.")
        if self._looks_like_feedback(mission_text):
            score -= 0.25
            warnings.append("La misión parece feedback, agradecimiento o cierre; no es material para neurona.")
            recommendations.append("Mover este contenido a Qualia o learning_candidate, no a una neurona.")
        if len(spec.mission.strip()) < 30:
            score -= 0.10
            warnings.append("Misión demasiado corta para uso operativo repetible.")
            recommendations.append("Agregar utilidad futura, dominio y evidencia mínima.")
        if not self._looks_like_operational_need(mission_text):
            score -= 0.08
            warnings.append("No se detecta necesidad operacional repetible.")
            recommendations.append("Explicar la repetición, el dominio y el impacto esperado.")

        score = round(max(0.0, min(score, 1.0)), 2)

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

        recommendations.append("No consolidar como estable sin pruebas y evidencia repetida.")

        return NeuronTrainingResult(
            name=spec.name,
            score=score,
            status=status,
            strengths=strengths,
            warnings=warnings,
            recommendations=recommendations,
            required_human_review=False,
        )

    @staticmethod
    def _looks_like_literal_question(text: str) -> bool:
        question_hints = (
            "en que",
            "en qué",
            "que significa",
            "qué significa",
            "cuanto es",
            "cuánto es",
            "donde queda",
            "dónde queda",
            "quien es",
            "quién es",
        )
        return "?" in text or any(hint in text for hint in question_hints)

    @staticmethod
    def _looks_like_feedback(text: str) -> bool:
        hints = (
            "muy bien",
            "muy bine",
            "felicitaciones",
            "gracias",
            "perfecto",
            "bien hecho",
            "excelente",
            "ok perfecto",
        )
        return any(hint in text for hint in hints)

    @staticmethod
    def _looks_like_operational_need(text: str) -> bool:
        hints = (
            "auditar",
            "auditoria",
            "auditoría",
            "operacional",
            "operativo",
            "repetible",
            "evitar contradicciones",
            "mantenimiento",
            "soporte",
            "monitoreo",
            "diagnosticar",
            "automatizar",
            "memoria",
            "federacion",
            "federación",
            "android",
            "llama.cpp",
            "formar",
            "evaluar",
            "validar",
            "verificable",
            "aprendizaje",
        )
        return any(hint in text for hint in hints)
