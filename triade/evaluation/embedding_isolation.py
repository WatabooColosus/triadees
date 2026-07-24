"""Aislamiento formal entre embeddings y evaluación.

Garantiza que los embeddings (vectorización, búsqueda semántica)
nunca influyan directamente en las métricas de evaluación/medición.
El flujo es unidireccional: evaluación → evidencia → consolidación.
Los embeddings son un servicio de soporte, no un input de decisión.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class IsolationBoundary:
    """Define la frontera entre subsistemas."""

    upstream: str
    downstream: str
    data_flow: str
    invariant: str


EMBEDDING_EVALUATION_BOUNDARIES: tuple[IsolationBoundary, ...] = (
    IsolationBoundary(
        upstream="semantic_embedding_engine",
        downstream="evaluation_runner",
        data_flow="NO_FLOW",
        invariant="Los vectores de embedding NUNCA se usan como input directo de BenchmarkCase.",
    ),
    IsolationBoundary(
        upstream="semantic_search",
        downstream="regression_gate",
        data_flow="NO_FLOW",
        invariant="Los scores de similaridad semántica NUNCA se usan como métrica de regresión.",
    ),
    IsolationBoundary(
        upstream="evaluation_runner",
        downstream="semantic_embedding_engine",
        data_flow="INDIRECT_VIA_DOCUMENT",
        invariant="El resultado de evaluación solo crea documentos semánticos vía consolidate().",
    ),
)


class EmbeddingEvaluationIsolator:
    """Verifica y documenta la separación entre embeddings y evaluación."""

    def __init__(self) -> None:
        self._boundaries = EMBEDDING_EVALUATION_BOUNDARIES

    def check_boundary(self, upstream: str, downstream: str) -> dict[str, Any]:
        for boundary in self._boundaries:
            if boundary.upstream == upstream and boundary.downstream == downstream:
                return {
                    "allowed": boundary.data_flow == "INDIRECT_VIA_DOCUMENT",
                    "flow_type": boundary.data_flow,
                    "invariant": boundary.invariant,
                }
        return {"allowed": False, "flow_type": "UNKNOWN", "invariant": "Frontera no definida; flujo bloqueado por defecto."}

    def validate_metric_source(self, metric_id: str, source_module: str) -> dict[str, Any]:
        embedding_modules = {"semantic_embedding_engine", "semantic_search", "semantic_store"}
        if source_module in embedding_modules:
            return {
                "valid": False,
                "reason": f"Métrica '{metric_id}' no puede derivar de módulo de embeddings '{source_module}'.",
                "violation": "EMBEDDING_EVALUATION_ISOLATION",
            }
        return {"valid": True, "reason": "Fuente de métrica compatible con aislamiento.", "violation": None}

    def audit(self) -> dict[str, Any]:
        return {
            "status": "active",
            "boundaries": len(self._boundaries),
            "invariants": [b.invariant for b in self._boundaries],
            "rule": "Los embeddings son servicio de soporte. La evaluación es el árbitro de calidad. Nunca se cruzan directamente.",
        }

    def validate_consolidation(self, candidate_id: str, measurement_source: str) -> dict[str, Any]:
        """Valida que la evidencia de medición no provenga de módulos de embeddings.

        Llamar desde LearningPipeline.consolidate() antes de promover a stable.
        Si measurement_source es un módulo de embeddings, la consolidación se bloquea.
        """
        embedding_modules = {"semantic_embedding_engine", "semantic_search", "semantic_store", "embedding_isolation"}
        if measurement_source in embedding_modules:
            return {
                "allowed": False,
                "reason": (
                    f"Consolidación bloqueada: la evidencia de medición del candidato '{candidate_id}' "
                    f"provino del módulo de embeddings '{measurement_source}', lo cual viola el Artículo IV "
                    f"de la Constitución (Medición Independiente)."
                ),
                "violation": "EMBEDDING_EVALUATION_ISOLATION",
            }
        return {"allowed": True, "reason": "Fuente de medición compatible con aislamiento.", "violation": None}


GLOBAL_ISOLATOR = EmbeddingEvaluationIsolator()
