"""Búsqueda autónoma por incertidumbre, siempre candidate-only."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from triade.core.guarded_web import guarded_web_research, requests_web_research
from triade.learning.pipeline import LearningPipeline


@dataclass(frozen=True, slots=True)
class AutonomousResearchPolicy:
    enabled: bool = True
    maximum_queries_per_day: int = 12
    minimum_memory_confidence: float = 0.55
    maximum_sources: int = 3
    minimum_excerpt_chars: int = 120


SCHEMA = """
CREATE TABLE IF NOT EXISTS autonomous_research_runs (
  research_id TEXT PRIMARY KEY, query TEXT NOT NULL, trigger TEXT NOT NULL,
  status TEXT NOT NULL, sources_json TEXT NOT NULL, source_hash TEXT NOT NULL,
  candidate_ids_json TEXT NOT NULL, contradictions_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

SENSITIVE = re.compile(
    r"\b(password|contrase(?:ña|na)|token|credencial|malware|exploit|arma|autolesi[oó]n|datos privados)\b",
    re.I,
)
FACTUAL = re.compile(
    r"\b(qué|que|quién|quien|cuál|cual|cómo|como|cuándo|cuando|dónde|donde|por qué|porque|explica|investiga)\b",
    re.I,
)
LOCAL_IDENTITY = re.compile(
    r"\b(recuerd|memoria|sesiones?|identidad|quién eres|quien eres|cómo te llamas|como te llamas|triade)\w*\b",
    re.I,
)


class AutonomousResearchEngine:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        *,
        policy: AutonomousResearchPolicy | None = None,
        search_provider: Callable[..., dict[str, Any]] = guarded_web_research,
    ) -> None:
        self.db_path = Path(db_path)
        self.policy = policy or AutonomousResearchPolicy()
        self.search_provider = search_provider
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def should_research(
        self,
        query: str,
        *,
        memory_confidence: float,
        authorized_matches: int,
        model_uncertain: bool = False,
    ) -> tuple[bool, str]:
        if not self.policy.enabled:
            return False, "disabled"
        if SENSITIVE.search(query):
            return False, "sensitive_query"
        if requests_web_research(query):
            return True, "explicit_request"
        if LOCAL_IDENTITY.search(query):
            return False, "local_identity_question"
        if not FACTUAL.search(query):
            return False, "not_factual"
        if (
            authorized_matches > 0
            and memory_confidence >= self.policy.minimum_memory_confidence
            and not model_uncertain
        ):
            return False, "memory_sufficient"
        if self._queries_today() >= self.policy.maximum_queries_per_day:
            return False, "daily_quota"
        return True, "knowledge_gap"

    def research(self, query: str, *, trigger: str = "knowledge_gap") -> dict[str, Any]:
        result = self.search_provider(query, max_sources=self.policy.maximum_sources)
        return self.ingest_result(query, result, trigger=trigger)

    def ingest_result(
        self, query: str, result: dict[str, Any], *, trigger: str = "explicit_request"
    ) -> dict[str, Any]:
        """Registra fuentes ya obtenidas sin repetir la consulta de red."""
        sources = []
        query_terms = self._terms(query)
        for raw in result.get("sources", []):
            excerpt = str(raw.get("excerpt", ""))
            title = str(raw.get("title", ""))
            overlap = query_terms & self._terms(title + " " + excerpt)
            relevance = len(overlap) / max(1, len(query_terms))
            minimum_relevance = (
                0.10 if raw.get("source_type") == "primary_documentation" else 0.20
            )
            if (
                len(excerpt) < self.policy.minimum_excerpt_chars
                or relevance < minimum_relevance
            ):
                continue
            source = {
                **raw,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "relevance_score": round(relevance, 3),
                "reputation": self._reputation(str(raw.get("url", ""))),
                "provenance_status": "candidate_evidence",
            }
            sources.append(source)
        contradictions = self._contradictions(sources)
        candidates: list[str] = []
        pipeline = LearningPipeline(self.db_path)
        for source in sources:
            payload = pipeline.ingest(
                content=str(source.get("excerpt", "")),
                source_type="web",
                source_ref=str(source.get("url", "")),
                title=str(source.get("title", "Fuente web")),
                domain="web_research",
                risk_level="low",
            )
            if payload.get("candidate_id"):
                candidates.append(payload["candidate_id"])
        canonical = json.dumps(sources, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        rid = f"web-{digest[:16]}-{int(datetime.now(timezone.utc).timestamp())}"
        status = "candidate_created" if candidates else "no_evidence"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO autonomous_research_runs VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    query,
                    trigger,
                    status,
                    canonical,
                    digest,
                    json.dumps(candidates),
                    json.dumps(contradictions),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return {
            "research_id": rid,
            "status": status,
            "query": query,
            "trigger": trigger,
            "sources": sources,
            "source_hash": digest,
            "candidate_ids": candidates,
            "contradictions": contradictions,
            "stable_memory_written": False,
        }

    def _queries_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM autonomous_research_runs WHERE created_at LIKE ?",
                    (today + "%",),
                ).fetchone()[0]
            )

    @staticmethod
    def _contradictions(sources: list[dict[str, Any]]) -> list[str]:
        excerpts = [str(s.get("excerpt", "")).lower() for s in sources]
        flags = []
        for i, left in enumerate(excerpts):
            for right in excerpts[i + 1 :]:
                if (" no " in left and " sí " in right) or (
                    " sí " in left and " no " in right
                ):
                    flags.append(
                        "Fuentes contienen afirmaciones potencialmente opuestas; requiere verificación independiente."
                    )
                    return flags
        return flags

    @staticmethod
    def _terms(text: str) -> set[str]:
        stop = {
            "para",
            "como",
            "qué",
            "que",
            "una",
            "unos",
            "las",
            "los",
            "del",
            "con",
            "por",
            "internet",
            "web",
        }
        return {
            w for w in re.findall(r"[a-záéíóúñ0-9]{3,}", text.lower()) if w not in stop
        }

    @staticmethod
    def _reputation(url: str) -> str:
        host = url.lower()
        if any(
            x in host for x in (".gov", ".edu", "docs.", "readthedocs", "wikipedia.org")
        ):
            return "established"
        return "unrated"
