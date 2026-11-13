"""Fábrica controlada de neuronas de Tríade Ω."""

from .candidate import NeuronCandidate, NeuronCandidateFactory
from .evaluation import NeuronEvaluationCoordinator
from .execution import SandboxExecutionEngine
from .exporter import NeuronLifecycleExporter
from .lifecycle import NeuronLifecycleManager
from .specification import (
    VALID_NEURON_STATES,
    VALID_TRANSITIONS,
    NeuronSpecification,
    ResourceBudget,
    validate_transition,
)
from .store import NeuronSpecificationStore

__all__ = [
    "VALID_NEURON_STATES",
    "VALID_TRANSITIONS",
    "NeuronCandidate",
    "NeuronCandidateFactory",
    "NeuronEvaluationCoordinator",
    "NeuronLifecycleExporter",
    "NeuronLifecycleManager",
    "NeuronSpecification",
    "NeuronSpecificationStore",
    "ResourceBudget",
    "SandboxExecutionEngine",
    "validate_transition",
]
