"""Fábrica controlada de neuronas de Tríade Ω."""

from .specification import (
    VALID_NEURON_STATES,
    VALID_TRANSITIONS,
    NeuronSpecification,
    ResourceBudget,
    validate_transition,
)
from .store import NeuronSpecificationStore

__all__ = [
    "NeuronSpecification",
    "NeuronSpecificationStore",
    "ResourceBudget",
    "VALID_NEURON_STATES",
    "VALID_TRANSITIONS",
    "validate_transition",
]
