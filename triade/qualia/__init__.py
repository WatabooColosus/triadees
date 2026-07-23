"""QualiaBus: capa circulatoria e introspectiva de experiencias de Tríade."""

from .contracts import (
    CentralKnowledgePacket,
    NeuronExperience,
    QualiaSignal,
    QualiaState,
    StorageMemoryPacket,
)
from .bus import QualiaBus
from .introspection import IntrospectionReport, QualiaIntrospector
from .router import QualiaRouter, QualiaBundle
from .store import QualiaStore

__all__ = [
    "CentralKnowledgePacket",
    "IntrospectionReport",
    "NeuronExperience",
    "QualiaBus",
    "QualiaBundle",
    "QualiaIntrospector",
    "QualiaRouter",
    "QualiaSignal",
    "QualiaState",
    "QualiaStore",
    "StorageMemoryPacket",
]
