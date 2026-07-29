"""QualiaBus: capa circulatoria e introspectiva de experiencias de Tríade."""

from .bus import QualiaBus
from .continuity import ContinuityEngine
from .contracts import (
    CentralKnowledgePacket,
    NeuronExperience,
    QualiaSignal,
    QualiaState,
    StorageMemoryPacket,
)
from .fragmentation import FragmentationDetector
from .introspection import IntrospectionReport, QualiaIntrospector
from .meaning import MeaningEngine
from .qualia_packet import (
    ContinuityChain,
    FragmentationReport,
    MeaningScore,
    QualiaPacket,
    build_qualia_packet,
)
from .router import QualiaBundle, QualiaRouter
from .store import QualiaStore

__all__ = [
    "CentralKnowledgePacket",
    "ContinuityChain",
    "ContinuityEngine",
    "FragmentationDetector",
    "FragmentationReport",
    "IntrospectionReport",
    "MeaningEngine",
    "MeaningScore",
    "NeuronExperience",
    "QualiaBundle",
    "QualiaBus",
    "QualiaIntrospector",
    "QualiaPacket",
    "QualiaRouter",
    "QualiaSignal",
    "QualiaState",
    "QualiaStore",
    "StorageMemoryPacket",
    "build_qualia_packet",
]
