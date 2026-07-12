"""Contratos formales para la creación controlada de neuronas."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

VALID_NEURON_STATES = {
    "draft",
    "specified",
    "training",
    "evaluated",
    "promoted",
    "rejected",
    "quarantined",
    "retired",
}

VALID_TRANSITIONS = {
    "draft": {"specified", "rejected"},
    "specified": {"training", "rejected"},
    "training": {"evaluated", "quarantined", "rejected"},
    "evaluated": {"promoted", "quarantined", "rejected"},
    "promoted": {"quarantined", "retired"},
    "quarantined": {"training", "rejected", "retired"},
    "rejected": set(),
    "retired": set(),
}


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    max_memory_mb: int
    max_runtime_seconds: int
    max_storage_mb: int

    def validate(self) -> None:
        values = (self.max_memory_mb, self.max_runtime_seconds, self.max_storage_mb)
        if any(value <= 0 for value in values):
            raise ValueError("el presupuesto de recursos debe ser positivo")


@dataclass(frozen=True, slots=True)
class NeuronSpecification:
    neuron_id: str
    name: str
    mission: str
    domain: str
    version: str
    owner: str
    component: str
    input_contract: dict[str, Any]
    output_contract: dict[str, Any]
    provides_capabilities: tuple[str, ...]
    requires_capabilities: tuple[str, ...] = ()
    evaluation_suites: tuple[str, ...] = ()
    rollback_policy: str | None = None
    training_policy: str = "configuration"
    sandbox_required: bool = True
    critical: bool = False
    resource_budget: ResourceBudget | None = None
    state: str = "draft"

    def validate(self) -> None:
        required = (
            self.neuron_id,
            self.name,
            self.mission,
            self.domain,
            self.version,
            self.owner,
            self.component,
        )
        if not all(value.strip() for value in required):
            raise ValueError("campos obligatorios incompletos")
        if self.state not in VALID_NEURON_STATES:
            raise ValueError(f"estado inválido: {self.state}")
        if not self.input_contract or not self.output_contract:
            raise ValueError("la neurona requiere contratos de entrada y salida")
        if not self.provides_capabilities:
            raise ValueError("la neurona debe proporcionar al menos una capacidad")
        if set(self.provides_capabilities) & set(self.requires_capabilities):
            raise ValueError("una capacidad no puede ser requerida y proporcionada a la vez")
        if not self.sandbox_required:
            raise ValueError("toda neurona nueva debe iniciar en sandbox")
        if self.resource_budget is None:
            raise ValueError("la neurona requiere presupuesto de recursos")
        self.resource_budget.validate()
        if self.critical and (not self.evaluation_suites or not self.rollback_policy):
            raise ValueError("una neurona crítica requiere suite y rollback")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_transition(current: str, target: str) -> None:
    if current not in VALID_TRANSITIONS or target not in VALID_NEURON_STATES:
        raise ValueError("estado desconocido")
    if target not in VALID_TRANSITIONS[current]:
        raise ValueError(f"transición inválida: {current} -> {target}")
