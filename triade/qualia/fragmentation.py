"""FragmentationDetector: detecta fragmentación y deriva en experiencias Qualia.

Mide la coherencia entre experiencias dentro de un mismo run.
Si las experiencias son incompatibles o saltan de tema bruscamente,
genera un reporte con acción recomendada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import NeuronExperience, QualiaState


@dataclass(slots=True)
class TopicCluster:
    """Cluster temático: agrupa experiencias por tema dominante."""

    topic: str = ""
    keywords: list[str] = field(default_factory=list)
    count: int = 0
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "keywords": list(self.keywords),
            "count": self.count,
            "evidence": list(self.evidence[:5]),
        }


TOPIC_SEEDS: dict[str, list[str]] = {
    "mission": ["misión", "objetivo", "entregar", "cumplir", "plan", "tarea"],
    "learning": ["aprender", "conocimiento", "patrón", "descubrir", "hipótesis", "memoria"],
    "safety": ["seguridad", "riesgo", "protección", "amenaza", "límite", " ética"],
    "self": ["estado", "emoción", "introspección", "carga", "fatiga", "qualia"],
    "error": ["error", "fallo", "excepción", "problema", "crash", "falló"],
    "infrastructure": ["sistema", "servidor", "gpu", "ram", "disco", "proceso"],
    "communication": ["usuario", "respuesta", "pregunta", "comunicación", "mensaje"],
}


class FragmentationDetector:
    """Detecta fragmentación cualitativa en un conjunto de experiencias.

    No necesita DB: opera sobre listas en memoria.
    Persistencia es opcional vía report().
    """

    def __init__(self) -> None:
        self._topic_seeds = TOPIC_SEEDS

    def detect(
        self,
        *,
        experiences: list[NeuronExperience | dict[str, Any]],
        state: QualiaState | None = None,
    ) -> dict[str, Any]:
        """Analiza un lote de experiencias y devuelve un FragmentationReport dict."""
        rows = [self._as_dict(e) for e in experiences]

        if not rows:
            return {
                "coherence_score": 1.0,
                "drift_detected": False,
                "contradictions": [],
                "topic_jump_count": 0,
                "recommended_action": "no_data",
            }

        clusters = self._cluster_topics(rows)
        contradictions = self._detect_contradictions(rows)
        topic_jumps = self._count_topic_jumps(rows, clusters)

        coherence = self._compute_coherence(
            len(rows), len(clusters), topic_jumps, len(contradictions)
        )

        drift = coherence < 0.5 or topic_jumps >= 3
        action = self._recommend_action(coherence, drift, len(contradictions), len(rows))

        return {
            "coherence_score": round(coherence, 4),
            "drift_detected": drift,
            "contradictions": contradictions,
            "topic_jump_count": topic_jumps,
            "recommended_action": action,
        }

    def _cluster_topics(self, rows: list[dict[str, Any]]) -> list[TopicCluster]:
        clusters: dict[str, TopicCluster] = {}
        for row in rows:
            text = self._combined_text(row)
            assigned = False
            for topic, seeds in self._topic_seeds.items():
                hits = [s for s in seeds if s in text]
                if hits:
                    if topic not in clusters:
                        clusters[topic] = TopicCluster(topic=topic, keywords=seeds[:3])
                    clusters[topic].count += 1
                    clusters[topic].evidence.append(text[:120])
                    assigned = True
                    break
            if not assigned:
                if "other" not in clusters:
                    clusters["other"] = TopicCluster(topic="other")
                clusters["other"].count += 1
                clusters["other"].evidence.append(text[:120])
        return list(clusters.values())

    def _detect_contradictions(self, rows: list[dict[str, Any]]) -> list[str]:
        claims: dict[str, dict[str, set[str]]] = {}
        for row in rows:
            subject = str(row.get("mission") or row.get("source") or "general").lower()
            obs = str(row.get("observation", "")).lower()
            if not obs:
                continue
            negative_tokens = (" no ", "nunca", "falso", "incorrecto", "falló", "imposible")
            polarity = "negative" if any(t in obs for t in negative_tokens) else "positive"
            claims.setdefault(subject, {}).setdefault(polarity, set()).add(obs[:80])

        contradictions = []
        for subject, pols in claims.items():
            if {"positive", "negative"} <= set(pols.keys()):
                contradictions.append(
                    f"Polaridad opuesta sobre '{subject}': "
                    f"{len(pols['positive'])} pos, {len(pols['negative'])} neg"
                )
        return contradictions

    def _count_topic_jumps(
        self, rows: list[dict[str, Any]], clusters: list[TopicCluster]
    ) -> int:
        if len(rows) < 2 or not clusters:
            return 0

        topic_sequence = []
        for row in rows:
            text = self._combined_text(row)
            found = "other"
            for topic, seeds in self._topic_seeds.items():
                if any(s in text for s in seeds):
                    found = topic
                    break
            topic_sequence.append(found)

        jumps = 0
        for i in range(1, len(topic_sequence)):
            if topic_sequence[i] != topic_sequence[i - 1]:
                jumps += 1
        return jumps

    def _compute_coherence(
        self,
        num_rows: int,
        num_clusters: int,
        topic_jumps: int,
        num_contradictions: int,
    ) -> float:
        if num_rows == 0:
            return 1.0

        cluster_ratio = 1.0 - min(1.0, (num_clusters - 1) / max(1, num_rows))
        jump_penalty = min(1.0, topic_jumps / max(1, num_rows - 1)) * 0.5
        contradiction_penalty = min(1.0, num_contradictions * 0.3)

        coherence = cluster_ratio - jump_penalty - contradiction_penalty
        return max(0.0, min(1.0, coherence))

    def _recommend_action(
        self,
        coherence: float,
        drift: bool,
        num_contradictions: int,
        num_rows: int,
    ) -> str:
        if num_rows == 0:
            return "no_data"
        if num_contradictions >= 2:
            return "resolve_contradictions"
        if drift:
            return "refocus_topic"
        if coherence < 0.7:
            return "increase_focus"
        return "continue"

    def _combined_text(self, row: dict[str, Any]) -> str:
        parts = [
            str(row.get("observation", "")),
            str(row.get("extracted_pattern", "")),
            str(row.get("mission", "")),
            str(row.get("source", "")),
        ]
        return " ".join(parts).lower()

    @staticmethod
    def _as_dict(item: NeuronExperience | dict[str, Any]) -> dict[str, Any]:
        if isinstance(item, NeuronExperience):
            return item.to_dict()
        return dict(item)
