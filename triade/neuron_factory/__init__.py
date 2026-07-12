"""Fábrica controlada de neuronas de Tríade Ω."""

from .candidates import NeuronCandidate, NeuronCandidateFactory
from .specification import (
    VALID_NEURON_STATES,
    VALID_TRANSITIONS,
    NeuronSpecification,
    ResourceBudget,
    validate_transition,
)
from .store import NeuronSpecificationStore
from .validation import NeuronSpecificationValidator, SpecificationValidationResult

__all__ = [
    "NeuronCandidate",
    "NeuronCandidateFactory",
    "NeuronSpecification",
    "NeuronSpecificationStore",
    "NeuronSpecificationValidator",
    "ResourceBudget",
    "SpecificationValidationResult",
    "VALID_NEURON_STATES",
    "VALID_TRANSITIONS",
    "validate_transition",
]
