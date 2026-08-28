"""Contratos del ciclo limitado de auto-mejora."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

VALID_RISK_LEVELS = {"low", "medium", "high", "critical"}


@dataclass(frozen=True, slots=True)
class ImprovementSignal:
    signal_id: str
    capability_id: str
    metric_id: str
    observed_score: float
    target_score: float
    impact: float
    confidence: float
    estimated_cost: float
    risk_level: str = "low"
    source_ref: str | None = None

    def validate(self) -> None:
        if not all(
            (self.signal_id.strip(), self.capability_id.strip(), self.metric_id.strip())
        ):
            raise ValueError("signal_id, capability_id y metric_id son obligatorios")
        if self.risk_level not in VALID_RISK_LEVELS:
            raise ValueError(f"nivel de riesgo inválido: {self.risk_level}")
        if not 0 <= self.observed_score <= 1 or not 0 <= self.target_score <= 1:
            raise ValueError("las puntuaciones deben estar entre 0 y 1")
        if self.target_score <= self.observed_score:
            raise ValueError("target_score debe superar observed_score")
        if not 0 <= self.impact <= 1 or not 0 <= self.confidence <= 1:
            raise ValueError("impact y confidence deben estar entre 0 y 1")
        if self.estimated_cost <= 0:
            raise ValueError("estimated_cost debe ser positivo")

    def priority(self) -> float:
        self.validate()
        gap = self.target_score - self.observed_score
        risk_penalty = {"low": 1.0, "medium": 0.8, "high": 0.5, "critical": 0.2}[
            self.risk_level
        ]
        return (
            gap * self.impact * self.confidence * risk_penalty
        ) / self.estimated_cost

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["priority"] = self.priority()
        return payload


@dataclass(frozen=True, slots=True)
class ImprovementProposal:
    proposal_id: str
    signal_id: str
    hypothesis: str
    requested_capability: str
    requires_human_approval: bool
    max_candidates: int = 1
    cooldown_seconds: int = 3600
    #: A qué neurona y versión se le construye la candidata.
    #:
    #: Faltaban, y su ausencia era un contrato roto entre productor y consumidor:
    #: `_self_improvement_evaluation` exige `payload["neuron_id"]` y
    #: `payload["version"]`, el store escribe en `payload_json` exactamente los
    #: campos de esta clase, y aquí no existían. **Ninguna propuesta creada por
    #: la vía soportada podía pasar de la aprobación**, hiciera lo que hiciera
    #: quien la creara. Comprobado el 2026-08-27 sobre la base viva: la única
    #: propuesta se aprobó sola por primera vez y murió en
    #: «la propuesta aprobada no declara neuron_id/version».
    #:
    #: Se dejan opcionales a propósito. Resolverlos desde la capacidad exigiría
    #: que alguna neurona declarara `provides_capabilities`, y eso lo escribe
    #: `neuron_specifications` —que se puebla *después* de aprobar—: derivarlos
    #: ahí sería cerrar otro círculo. Quien propone una mejora sabe a qué apunta;
    #: si no lo sabe, el handler lo dice con ese nombre y no como propuesta
    #: malformada.
    neuron_id: str | None = None
    version: str | None = None

    def validate(self) -> None:
        required = (
            self.proposal_id,
            self.signal_id,
            self.hypothesis,
            self.requested_capability,
        )
        if not all(value.strip() for value in required):
            raise ValueError("campos obligatorios incompletos")
        if self.max_candidates < 1:
            raise ValueError("max_candidates debe ser al menos 1")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds no puede ser negativo")
        # Declarar el objetivo a medias es peor que no declararlo: el handler
        # necesita la terna completa para su clave de idempotencia.
        if bool(self.neuron_id) != bool(self.version):
            raise ValueError("neuron_id y version se declaran juntos o ninguno")
