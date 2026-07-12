"""Fábrica controlada de neuronas de Tríade Ω."""

from .candidate import NeuronCandidate, NeuronCandidateFactory
from .execution import SandboxExecutionEngine
from .specification import (
    VALID_NEURON_STATES,
    VALID_TRANSITIONS,
    NeuronSpecification,
    ResourceBudget,
    validate_transition,
)
from .store import NeuronSpecificationStore

__all__ = [
    "NeuronCandidate",
    "NeuronCandidateFactory",
    "NeuronSpecification",
    "NeuronSpecificationStore",
    "ResourceBudget",
    "SandboxExecutionEngine",
    "VALID_NEURON_STATES",
    "VALID_TRANSITIONS",
    "validate_transition",
]
