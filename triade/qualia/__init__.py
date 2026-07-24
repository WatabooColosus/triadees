"""QualiaBus: capa circulatoria e introspectiva de experiencias de Tríade."""

from .contracts import (
    CentralKnowledgePacket,
    NeuronExperience,
    QualiaSignal,
    QualiaState,
    StorageMemoryPacket,
)
from .qualia_packet import (
    ContinuityChain,
    FragmentationReport,
    MeaningScore,
    QualiaPacket,
    build_qualia_packet,
)
from .continuity import ContinuityEngine
from .meaning import MeaningEngine
from .fragmentation import FragmentationDetector
from .bus import QualiaBus
from .introspection import IntrospectionReport, QualiaIntrospector
from .router import QualiaRouter, QualiaBundle
from .store import QualiaStore

__all__ = [
    "CentralKnowledgePacket",
    "ContinuityEngine",
    "ContinuityChain",
    "FragmentationDetector",
    "FragmentationReport",
    "IntrospectionReport",
    "MeaningEngine",
    "MeaningScore",
    "NeuronExperience",
    "QualiaBus",
    "QualiaBundle",
    "QualiaIntrospector",
    "QualiaPacket",
    "QualiaRouter",
    "QualiaSignal",
    "QualiaState",
    "QualiaStore",
    "StorageMemoryPacket",
    "build_qualia_packet",
]
